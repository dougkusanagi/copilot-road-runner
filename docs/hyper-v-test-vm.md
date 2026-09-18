# VM de teste Hyper-V — desenvolver sem atrapalhar o uso do PC

> Host: **Windows 11 Pro**. O agente (`pyautogui`/`pywinauto`) rouba mouse e teclado
> de quem o executa — por isso ele roda **dentro do guest**, e o host fica livre.

## Topologia

* **HOST (seu PC, com GPU):** `llama-server` do planner (`:8091`, MiniCPM5-1B)
  + visão (`:8082`, Vocaela-2) + IDE. Nada que clique na tela roda aqui.
* **GUEST (`crr-test`, Hyper-V):** só o agente leve — `main.py`, `loop.py`,
  `uia.py`, `actions.py`, `tools.py` + `config.vm.json` apontando para o IP do host.
* **Isolamento:** o `pyautogui` do guest só enxerga o desktop do guest.
  Snapshot `clean` restaura tudo em segundos após teste destrutivo.

## Pré-requisitos

* Windows 11 Pro com virtualização ativa na BIOS/UEFI.
* ISO do Windows 10/11 para instalar o guest uma vez.
* ~60GB livres (VHDX dinâmico — ocupa só o usado) + 4GB RAM p/ o guest.

## Setup (uma vez)

**1. Criar a VM (PowerShell como admin, na raiz do repo):**

```powershell
.\scripts\New-TestVm.ps1 -IsoPath C:\ISOs\Win11.iso
```

Instale o Windows no guest pelo console do Hyper-V.

**2. Preparar o guest:**

* Python 3.12+ + `uv`, copiar a pasta do projeto
  (Enhanced Session permite copiar/colar arquivos pelo console).
* Resolução em **100%** (sem escala de DPI) — evita clique deslocado
  entre UIA, screenshot e `pyautogui`.
* `uv sync` dentro da pasta do projeto no guest.

**3. Expor os modelos no host:**

```powershell
.\scripts\New-TestVm.ps1 -OpenModelPorts
```

Suba os dois `llama-server` ouvindo na rede (`--host 0.0.0.0`),
não só em `127.0.0.1`. Descubra o IP do host alcançável do guest:

```powershell
ipconfig  # IPv4 do adaptador vEthernet (Default Switch)
```

**4. Config do guest:** copie `config.vm.example.json` → `config.vm.json`
(este último é local, ignorado pelo git) e troque `HOST_IP` pelo IP acima:

```powershell
Copy-Item config.vm.example.json config.vm.json  # dentro do guest
```

**5. Snapshot limpo (guest pronto: Windows + deps + projeto):**

```powershell
.\scripts\New-TestVm.ps1 -CreateCheckpoint
```

## Loop diário de testes

```powershell
# antes da bateria: volta ao limpo
.\scripts\Reset-TestVm.ps1
```

No guest, sempre nesta ordem:

```powershell
uv run python main.py --self-test          # sem clicar em nada
uv run python main.py "..." --config config.vm.json --max-steps 4
```

Depois da bateria (ou de qualquer teste destrutivo): `Reset-TestVm.ps1` de novo.

## Salvaguardas

* `pyautogui.FAILSAFE` ativo: canto superior-esquerdo **do guest** aborta;
  `Ctrl+Alt+Esc` (guest) também para o loop.
* Comece com `--max-steps 4`; aumente só após verde consistente.
* Nunca rode o agente no host enquanto usa o PC — é exatamente o que a VM evita.

## Troubleshooting

| Sintoma | Causa provável / fix |
|---|---|
| Guest não alcança `:8091`/`:8082` | `llama-server` preso em `127.0.0.1` → subir com `--host 0.0.0.0`; rodar script com `-OpenModelPorts`; conferir IP do `vEthernet` |
| IP do host mudou | Default Switch usa DHCP interno — após reboot, confira `ipconfig` e atualize `config.vm.json` |
| Clique deslocado no guest | Escala de DPI ≠ 100% no guest; Enhanced Session com resolução dinâmica — fixe 1920x1080 @100% |
| Hyper-V conflita com VirtualBox/VMware | No Win11, VirtualBox/VMware rodam sobre a plataforma Hyper-V (lento) — prefira só Hyper-V aqui |
| VM lenta | 2 vCPU bastam p/ o agente (modelos estão no host); não dê mais de metade dos cores físicos |

## Complemento, não substituto

**Windows Sandbox** (`.wsb`) serve para teste descartável único (boot ~10s,
sempre limpo), mas sem snapshot e reinstalando deps a cada abertura.
Hyper-V acima é o ambiente principal de desenvolvimento.
