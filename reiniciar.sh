#!/usr/bin/env bash
# Reinicia el servidor (waitress + cloudflared) tomando los nuevos cambios del codigo,
# o consulta su estado/logs/URL sin reiniciar nada.
# Uso: ./reiniciar.sh            (reinicia todo y muestra la URL nueva)
#       ./reiniciar.sh url       (muestra la URL publica actual)
#       ./reiniciar.sh logs      (muestra las ultimas lineas del log de cloudflared)
#       ./reiniciar.sh estado    (indica si waitress y cloudflared estan corriendo)
set -u

PROYECTO="/home/CDT/gmorello/Escritorio/backup25_06/scau"
WAITRESS="$HOME/.local/bin/waitress-serve"
CLOUDFLARED="$HOME/.local/bin/cloudflared"
PUERTO=5000

obtener_url() {
    grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" /tmp/cloudflared.log \
        | sort -u | head -1
}

COMANDO="${1:-}"
case "$COMANDO" in
    url)
        URL="$(obtener_url)"
        if [ -z "$URL" ]; then
            echo "No hay URL (cloudflared todavia no la expuso). Log: /tmp/cloudflared.log"
            exit 1
        fi
        echo "$URL"
        exit 0
        ;;
    logs)
        if [ ! -f /tmp/cloudflared.log ]; then
            echo "El log de cloudflared no existe: /tmp/cloudflared.log"
            exit 1
        fi
        tail -n 20 /tmp/cloudflared.log
        exit 0
        ;;
    estado)
        echo "--- waitress ---"
        pgrep -af "waitress-serve" || echo "  DETENIDO"
        echo "--- cloudflared ---"
        pgrep -af "cloudflared tunnel" || echo "  DETENIDO"
        echo "--- URL vigente ---"
        URL="$(obtener_url)"
        [ -n "$URL" ] && echo "  $URL" || echo "  sin URL todavia"
        exit 0
        ;;
    ayuda|help|-h|--help)
        echo "Uso: $0 [comando]"
        echo "  (sin comando)  Reinicia el servidor y muestra la URL nueva."
        echo "  url            Muestra la URL publica actual y sale."
        echo "  logs           Muestra el log de cloudflared (ultimas 20 lineas)."
        echo "  estado         Muestra si waitress y cloudflared estan corriendo."
        exit 0
        ;;
esac

echo "[1/4] Deteniendo procesos viejos..."
pkill -f "waitress-serve" 2>/dev/null
pkill -f "cloudflared tunnel" 2>/dev/null
sleep 2

if pgrep -f "waitress-serve" >/dev/null || pgrep -f "cloudflared tunnel" >/dev/null; then
    echo "Error: no se pudieron detener los procesos. Revisar con: ps aux | grep -E 'waitress|cloudflared'"
    exit 1
fi

echo "[2/4] Levantando la app (waitress, puerto $PUERTO)..."
cd "$PROYECTO" || exit 1
setsid nohup "$WAITRESS" --listen=0.0.0.0:$PUERTO --threads=32 app:app \
    > /tmp/waitress.log 2>&1 < /dev/null &
disown

sleep 2
CODIGO=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PUERTO/" || echo "000")
if [ "$CODIGO" != "200" ]; then
    echo "Error: la app no respondio (HTTP $CODIGO). Log: /tmp/waitress.log"
    tail -5 /tmp/waitress.log
    exit 1
fi
echo "    App OK (HTTP 200)."

echo "[3/4] Abriendo el tunel de cloudflared..."
setsid nohup "$CLOUDFLARED" tunnel --url "http://localhost:$PUERTO" \
    > /tmp/cloudflared.log 2>&1 < /dev/null &
disown

sleep 10
URL="$(obtener_url)"
if [ -z "$URL" ]; then
    echo "Error: cloudflared no expuso ninguna URL. Log: /tmp/cloudflared.log"
    exit 1
fi

echo "[4/4] Verificando url publica..."
CODIGO=$(curl -s -o /dev/null -w "%{http_code}" "${URL}/" || echo "000")
if [ "$CODIGO" != "200" ]; then
    echo "Error: la URL publica no responde (HTTP $CODIGO)."
    exit 1
fi

echo ""
echo "======================================================================"
echo "  SERVIDOR REINICIADO CON LOS NUEVOS CAMBIOS"
echo ""
echo "  URL NUEVA (CAMBIÓ, es la que hay que reenviar a los meseros):"
echo "  $URL"
echo ""
echo "  Meseros:  $URL/"
echo "  Caja:     $URL/caja"
echo "  Cocina:   $URL/cocina"
echo "======================================================================"