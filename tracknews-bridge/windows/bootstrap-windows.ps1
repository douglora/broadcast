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
#
# O resultado sai por $script:RegistroOk, nao pelo valor de retorno: em
# PowerShell tudo que a funcao escreve no fluxo de saida VIRA o retorno, entao
# um `if (Registra-Tarefa ...)` engoliria as proprias linhas OK/PENDENTE e nada
# apareceria na tela.
function Registra-Tarefa($nome, $arquivoXml, $descricao) {
  $script:RegistroOk = $false
  if (Get-ScheduledTask -TaskName $nome -ErrorAction SilentlyContinue) {
    OK "tarefa `"$nome`" ja existia"
    $script:RegistroOk = $true
    return
  }
  try {
    Register-ScheduledTask -TaskName $nome -Xml (Get-TaskXml $arquivoXml) -ErrorAction Stop | Out-Null
  } catch {
    PEND "registrar a tarefa `"$nome`" falhou: $($_.Exception.Message) -- $descricao"
    return
  }
  if (Get-ScheduledTask -TaskName $nome -ErrorAction SilentlyContinue) {
    OK "tarefa `"$nome`" registrada e confirmada"
    $script:RegistroOk = $true
  } else {
    PEND "a tarefa `"$nome`" nao aparece depois do registro -- $descricao"
  }
}

# --- 1. tarefa que sobe o Ubuntu do WSL no logon e o mantem vivo -------------
# Registrar tarefa na raiz da biblioteca do Agendador costuma exigir elevacao.
# Sem ela, cai no plano B: um .vbs na pasta Inicializar DO USUARIO, que dispensa
# privilegio e roda no mesmo momento (logon). O efeito e o mesmo: sobe o Ubuntu
# e o mantem vivo, para o timer da ponte voltar sozinho depois de queda de luz.
$vbsInicializar = Join-Path ([Environment]::GetFolderPath('Startup')) 'TrackNews-WSL-Autostart.vbs'

Registra-Tarefa 'TrackNews WSL Autostart' 'wsl-autostart-task.xml' `
  'caindo para o plano B da pasta Inicializar'
if ($script:RegistroOk) {
  Start-ScheduledTask -TaskName 'TrackNews WSL Autostart' -ErrorAction SilentlyContinue
  if (Test-Path $vbsInicializar) {
    INFO "o atalho de plano B em $vbsInicializar ficou redundante; pode apagar quando quiser"
  }
} else {
  try {
    Set-Content -Path $vbsInicializar -Encoding ASCII -ErrorAction Stop `
      -Value 'CreateObject("WScript.Shell").Run "wsl.exe -d Ubuntu --exec /bin/sh -c ""sleep infinity""", 0, False'
    if (Test-Path $vbsInicializar) {
      OK "plano B no lugar: $vbsInicializar sobe o Ubuntu no logon (sem precisar de administrador)"
      # Vale ja nesta sessao, sem esperar o proximo logon.
      Start-Process -FilePath 'wscript.exe' -ArgumentList "`"$vbsInicializar`"" -ErrorAction SilentlyContinue
    } else {
      PEND "nem a tarefa nem o atalho da pasta Inicializar puderam ser criados; o WSL nao vai subir sozinho apos reboot"
    }
  } catch {
    PEND "plano B falhou ($($_.Exception.Message)); o WSL nao vai subir sozinho apos reboot"
  }
}

# --- 2. tarefa da ponte, so quando o WSL nao tem systemd ---------------------
if ($ComBridgeTask) {
  Registra-Tarefa 'TrackNews Bridge' 'tracknews-bridge-task.xml' `
    'sem ela a ponte so roda enquanto houver terminal do WSL aberto'
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

# --- 5. diagnostico: quem ocupa as portas onde o WAHA costuma atender --------
# So leitura. Serve para achar o WAHA quando ele nao esta na 3000 -- e para
# saber quem esta na 3000 quando ela responde mas nao e o WAHA.
$portas = 3000, 3001, 3002, 3003, 8000, 8080, 4000, 21465
$viuAlguma = $false
foreach ($porta in $portas) {
  $conn = Get-NetTCPConnection -State Listen -LocalPort $porta -ErrorAction SilentlyContinue |
          Select-Object -First 1
  if ($conn) {
    $viuAlguma = $true
    $proc = (Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue).ProcessName
    if (-not $proc) { $proc = "pid $($conn.OwningProcess)" }
    INFO "porta $porta ouvindo no Windows, processo: $proc"
  }
}
if (-not $viuAlguma) {
  INFO 'nenhuma das portas usuais do WAHA esta ouvindo no lado Windows'
}

# --- 6. logon automatico: so conferir; a senha e do Douglas ------------------
$wl = Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon' -ErrorAction SilentlyContinue
if ($wl -and $wl.AutoAdminLogon -eq '1') {
  OK 'logon automatico ja ativo: depois de queda de luz o PC volta ate a area de trabalho sozinho'
} else {
  PEND 'logon automatico DESATIVADO: depois de queda de luz o PC para na tela de senha e nada roda ate alguem logar. Para ativar (decisao sua, pede a senha): Win+R > netplwiz > desmarcar "Os usuarios devem digitar um nome de usuario e uma senha"'
}
