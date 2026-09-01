# Lado Windows da ponte TrackNews. Chamado pelo bootstrap.sh de dentro do WSL
# (interop). Nao mexe em nenhuma tarefa, servico ou container que nao seja da
# ponte. Imprime linhas "OK ..." e "PENDENTE ..." que o bootstrap recolhe.
param([switch]$ComBridgeTask)
$ErrorActionPreference = 'Continue'
function OK($m)   { Write-Output ("OK       $m") }
function PEND($m) { Write-Output ("PENDENTE $m") }

# --- 1. tarefa que sobe o Ubuntu do WSL no logon e o mantem vivo -------------
try {
  if (Get-ScheduledTask -TaskName 'TrackNews WSL Autostart' -ErrorAction SilentlyContinue) {
    OK 'tarefa "TrackNews WSL Autostart" ja existia'
  } else {
    Register-ScheduledTask -TaskName 'TrackNews WSL Autostart' `
      -Xml (Get-Content -Raw (Join-Path $PSScriptRoot 'wsl-autostart-task.xml')) | Out-Null
    OK 'tarefa "TrackNews WSL Autostart" registrada'
  }
  Start-ScheduledTask -TaskName 'TrackNews WSL Autostart' -ErrorAction SilentlyContinue
} catch {
  PEND ('registrar a tarefa WSL Autostart falhou (' + $_.Exception.Message + '); rode como administrador: Register-ScheduledTask -TaskName "TrackNews WSL Autostart" -Xml (Get-Content -Raw .\wsl-autostart-task.xml)')
}

# --- 2. tarefa da ponte, so quando o WSL nao tem systemd ---------------------
if ($ComBridgeTask) {
  try {
    if (Get-ScheduledTask -TaskName 'TrackNews Bridge' -ErrorAction SilentlyContinue) {
      OK 'tarefa "TrackNews Bridge" ja existia'
    } else {
      Register-ScheduledTask -TaskName 'TrackNews Bridge' `
        -Xml (Get-Content -Raw (Join-Path $PSScriptRoot 'tracknews-bridge-task.xml')) | Out-Null
      OK 'tarefa "TrackNews Bridge" registrada (fallback sem systemd)'
    }
  } catch {
    PEND ('registrar a tarefa TrackNews Bridge falhou (' + $_.Exception.Message + ')')
  }
}

# --- 3. energia: no cabo, nunca suspender nem hibernar -----------------------
powercfg /change standby-timeout-ac 0 | Out-Null
if ($LASTEXITCODE -eq 0) { OK 'energia: suspensao no cabo desligada' }
else { PEND 'powercfg standby-timeout-ac 0 falhou; ajuste em Configuracoes > Energia > nunca suspender' }
powercfg /change hibernate-timeout-ac 0 | Out-Null
if ($LASTEXITCODE -eq 0) { OK 'energia: hibernacao no cabo desligada' }
else { PEND 'powercfg hibernate-timeout-ac 0 falhou; ajuste em Configuracoes > Energia' }

# --- 4. Docker Desktop junto com o Windows (o WAHA vive nele) ----------------
$dockerExe = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
if (Test-Path $dockerExe) {
  $run = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
  if (Get-ItemProperty -Path $run -Name 'Docker Desktop' -ErrorAction SilentlyContinue) {
    OK 'Docker Desktop ja inicia com o Windows'
  } else {
    try {
      Set-ItemProperty -Path $run -Name 'Docker Desktop' -Value ('"' + $dockerExe + '" -Autostart')
      OK 'Docker Desktop configurado para iniciar com o Windows'
    } catch {
      PEND 'nao consegui ligar o autostart do Docker Desktop; ligue em Docker Desktop > Settings > General > Start when you sign in'
    }
  }
} else {
  OK 'Docker Desktop nao encontrado em Program Files; se o WAHA roda por outro caminho, garanta que ele volte sozinho no boot'
}

# --- 5. logon automatico: so conferir; a senha e do Douglas ------------------
$wl = Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon' -ErrorAction SilentlyContinue
if ($wl -and $wl.AutoAdminLogon -eq '1') {
  OK 'logon automatico ja ativo: depois de queda de luz o PC volta ate a area de trabalho sozinho'
} else {
  PEND 'logon automatico DESATIVADO: depois de queda de luz o PC para na tela de senha e nada roda ate alguem logar. Para ativar (decisao sua, pede a senha): Win+R > netplwiz > desmarcar "Os usuarios devem digitar um nome de usuario e uma senha"'
}
