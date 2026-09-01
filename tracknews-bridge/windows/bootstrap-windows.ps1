# Lado Windows da ponte TrackNews. Chamado pelo bootstrap.sh de dentro do WSL
# (interop). Nao mexe em nenhuma tarefa, servico ou container que nao seja da
# ponte. Imprime linhas "OK ...", "INFO ..." e "PENDENTE ..." que o bootstrap
# recolhe para o resumo.
param([switch]$ComBridgeTask)
$ErrorActionPreference = 'Continue'
function OK($m)   { Write-Output ("OK       $m") }
function INFO($m) { Write-Output ("INFO     $m") }
function PEND($m) { Write-Output ("PENDENTE $m") }

# Register-ScheduledTask recebe o XML como string UTF-16. Se a declaracao disser
# encoding="UTF-8" o parser recusa com 0x8004131a ("nao e possivel alternar
# codificacao"). Os arquivos deste repo ja vem sem o atributo; tiramos aqui de
# novo para funcionar tambem com uma copia antiga do XML.
function Get-TaskXml($nome) {
  $bruto = Get-Content -Raw (Join-Path $PSScriptRoot $nome)
  return ($bruto -replace '(<\?xml[^>]*?)\s+encoding\s*=\s*"[^"]*"', '$1')
}

# Registra a tarefa e CONFERE que ela existe. Sem -ErrorAction Stop o erro do
# Register e nao-terminante: o catch nao dispara e a funcao mentiria "OK".
function Registra-Tarefa($nome, $arquivoXml, $descricao) {
  if (Get-ScheduledTask -TaskName $nome -ErrorAction SilentlyContinue) {
    OK "tarefa `"$nome`" ja existia"
    return $true
  }
  try {
    Register-ScheduledTask -TaskName $nome -Xml (Get-TaskXml $arquivoXml) -ErrorAction Stop | Out-Null
  } catch {
    PEND "registrar a tarefa `"$nome`" falhou: $($_.Exception.Message) -- $descricao"
    return $false
  }
  if (Get-ScheduledTask -TaskName $nome -ErrorAction SilentlyContinue) {
    OK "tarefa `"$nome`" registrada e confirmada"
    return $true
  }
  PEND "a tarefa `"$nome`" nao aparece depois do registro -- $descricao"
  return $false
}

# --- 1. tarefa que sobe o Ubuntu do WSL no logon e o mantem vivo -------------
if (Registra-Tarefa 'TrackNews WSL Autostart' 'wsl-autostart-task.xml' `
      'rode o PowerShell como administrador e tente de novo') {
  Start-ScheduledTask -TaskName 'TrackNews WSL Autostart' -ErrorAction SilentlyContinue
}

# --- 2. tarefa da ponte, so quando o WSL nao tem systemd ---------------------
if ($ComBridgeTask) {
  Registra-Tarefa 'TrackNews Bridge' 'tracknews-bridge-task.xml' `
    'sem ela a ponte so roda enquanto houver terminal do WSL aberto' | Out-Null
}

# --- 3. energia: no cabo, nunca suspender nem hibernar -----------------------
powercfg /change standby-timeout-ac 0 | Out-Null
if ($LASTEXITCODE -eq 0) { OK 'energia: suspensao no cabo desligada' }
else { PEND 'powercfg standby-timeout-ac 0 falhou; ajuste em Configuracoes > Energia > nunca suspender' }
powercfg /change hibernate-timeout-ac 0 | Out-Null
if ($LASTEXITCODE -eq 0) { OK 'energia: hibernacao no cabo desligada' }
else { PEND 'powercfg hibernate-timeout-ac 0 falhou; ajuste em Configuracoes > Energia' }

# --- 4. Docker Desktop junto com o Windows (se for por onde o WAHA roda) -----
$candidatos = @(
  (Join-Path $env:ProgramFiles        'Docker\Docker\Docker Desktop.exe'),
  (Join-Path ${env:ProgramFiles(x86)} 'Docker\Docker\Docker Desktop.exe'),
  (Join-Path $env:LOCALAPPDATA        'Docker\Docker Desktop.exe')
) | Where-Object { $_ -and (Test-Path $_) }

if ($candidatos) {
  $dockerExe = $candidatos[0]
  $run = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
  if (Get-ItemProperty -Path $run -Name 'Docker Desktop' -ErrorAction SilentlyContinue) {
    OK 'Docker Desktop ja inicia com o Windows'
  } else {
    try {
      Set-ItemProperty -Path $run -Name 'Docker Desktop' -Value ('"' + $dockerExe + '" -Autostart') -ErrorAction Stop
      OK 'Docker Desktop configurado para iniciar com o Windows'
    } catch {
      PEND 'nao consegui ligar o autostart do Docker Desktop; ligue em Docker Desktop > Settings > General > Start when you sign in'
    }
  }
} elseif (Get-Process 'Docker Desktop' -ErrorAction SilentlyContinue) {
  PEND 'Docker Desktop esta rodando mas nao achei o .exe nos caminhos usuais; ligue o autostart em Settings > General > Start when you sign in'
} else {
  INFO 'Docker Desktop nao encontrado no Windows; se o WAHA roda por dentro do WSL, quem cuida do retorno dele e a checagem do lado Linux'
}

# --- 5. logon automatico: so conferir; a senha e do Douglas ------------------
$wl = Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon' -ErrorAction SilentlyContinue
if ($wl -and $wl.AutoAdminLogon -eq '1') {
  OK 'logon automatico ja ativo: depois de queda de luz o PC volta ate a area de trabalho sozinho'
} else {
  PEND 'logon automatico DESATIVADO: depois de queda de luz o PC para na tela de senha e nada roda ate alguem logar. Para ativar (decisao sua, pede a senha): Win+R > netplwiz > desmarcar "Os usuarios devem digitar um nome de usuario e uma senha"'
}
