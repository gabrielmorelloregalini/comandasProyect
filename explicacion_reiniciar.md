# reiniciar.sh - Que hace cada comando

El script `reiniciar.sh` controla el servidor de la app (waitress) y el tunel
publico (cloudflared). Toda su informacion queda en dos archivos de log:
- `/tmp/waitress.log`   -> log de la app (waitress)
- `/tmp/cloudflared.log` -> log del tunel (cloudflared) y donde aparece la URL

## Comandos

### ./reiniciar.sh
Reinicio COMPLETO del servidor:
1. Detiene waitress y cloudflared.
2. Levanta la app de nuevo (toma los nuevos cambios del codigo).
3. Abre un tunel nuevo de cloudflared.
4. Muestra la URL publica NUEVA al final y la verifica (HTTP 200).

> IMPORTANTE: cada reinicio genera una URL DIFERENTE. Hay que reenviar la nueva
> a los meseros. Se usa para aplicar cambios de codigo ANTES del evento.

### ./reiniciar.sh url
Muestra la URL publica VIGENTE en este momento (la extrae del log de
cloudflared). No reinicia ni toca nada. Es la forma rapida de recuperar el link.

### ./reiniciar.sh logs
Muestra las ultimas 20 lineas del log de cloudflared (/tmp/cloudflared.log).
Sirve para ver si el tunel esta conectado o el motivo de algun fallo.

### ./reiniciar.sh estado
Muestra:
- Si waitress esta corriendo (y su PID).
- Si cloudflared esta corriendo (y su PID).
- La URL publica vigente (si hay).
No modifica nada.

### ./reiniciar.sh ayuda  (o help / -h / --help)
Imprime este resumen de comandos.

## Como usarlo en el evento

- Al llegar y prender la PC, si nada esta corriendo:
    ./reiniciar.sh            -> deja todo arriba y te da la URL para repartir.
- En cualquier momento de la noche, si se pierde el link:
    ./reiniciar.sh url        -> recupera la URL al instante (sin reiniciar).
- Para chequear que siga todo vivo:
    ./reiniciar.sh estado
- Para ver el log del tunel:
    ./reiniciar.sh logs

Recuerda: mientras NO se reinicie el servidor, la URL NO cambia. Los modos
`url`, `logs`, `estado`, `ayuda` nunca cambian la URL (no reinician nada).