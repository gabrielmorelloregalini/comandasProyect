const fmt = (n) => Number(n).toLocaleString("es-AR");
const $ = (sel) => document.querySelector(sel);

const CLAVE_OCULTOS = "scau_cocina_ocultos";

function getOcultos() {
  try {
    return new Set(JSON.parse(localStorage.getItem(CLAVE_OCULTOS) || "[]"));
  } catch (_) {
    return new Set();
  }
}

function guardarOcultos(ocultos) {
  localStorage.setItem(CLAVE_OCULTOS, JSON.stringify([...ocultos]));
}

let idsPrevios = new Set();
let textoBusqueda = "";

function chipsAderezos(lista) {
  if (!lista || lista.length === 0) return "";
  return lista.map((a) => `<span class="chip-aderezos">${a}</span>`).join(" ");
}

function tarjetaCocina(p, esNuevo) {
  const items = p.items.map((i) => `
    <div class="comanda-item-lista">
      <span><span class="cant">${i.cantidad} x</span>${i.nombre} ${chipsAderezos(i.aderezos)}</span>
    </div>`).join("");

  return `
    <div class="tarjeta cocina ${esNuevo ? "nuevo" : ""}" data-id="${p.id}">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <span class="comanda-numero">${p.numero}</span>
        <button class="btn btn-naranja ocultar" data-id="${p.id}">Ocultar</button>
      </div>
      <div class="comanda-meta">
        <span><b>Mesa:</b> ${p.mesa}</span>
        <span><b>Comprador:</b> ${p.comprador}</span>
        <span><b>Mesero:</b> ${p.mesero}</span>
        <span><b>Hora:</b> ${p.creado_en.slice(11, 16)}</span>
      </div>
      <div class="comanda-items">${items}</div>
    </div>`;
}

function filtrarComanda(p) {
  const q = textoBusqueda.toLowerCase();
  if (!q) return true;
  return (p.numero + " " + p.mesa + " " + p.comprador + " " + p.mesero).toLowerCase().includes(q);
}

async function cargar() {
  try {
    const res = await fetch("/api/pedidos?estado=cobrado&limit=500");
    const pedidos = await res.json();
    const ocultos = getOcultos();
    const porPreparar = pedidos
      .filter((p) => p.estado === "cobrado" && !ocultos.has(p.id))
      .sort((a, b) => b.id - a.id);
    const cobrados = porPreparar.filter(filtrarComanda);
    const resaltarBusqueda = (textoBusqueda.length > 0) && porPreparar.length !== cobrados.length;

    if (resaltarBusqueda) {
      $("#contador").textContent = cobrados.length + " coincidencia(s) de " + porPreparar.length + " pedido(s) por preparar";
    } else {
      $("#contador").textContent = porPreparar.length + " pedido(s) por preparar";
    }

    const zona = $("#zona-pedidos");
    const nuevos = cobrados.filter((p) => !idsPrevios.has(p.id));
    const idsActuales = new Set(cobrados.map((p) => p.id));

    if (cobrados.length === 0) {
      zona.innerHTML = '<div class="vacio">Esperando pedidos...</div>';
    } else {
      zona.innerHTML = cobrados
        .map((p) => tarjetaCocina(p, nuevos.some((n) => n.id === p.id)))
        .join("");
      zona.querySelectorAll(".ocultar").forEach((btn) => {
        btn.addEventListener("click", () => {
          const ocultos = getOcultos();
          ocultos.add(Number(btn.dataset.id));
          guardarOcultos(ocultos);
          btn.closest(".tarjeta").remove();
          const actuales = document.querySelectorAll("#zona-pedidos .tarjeta").length;
          $("#contador").textContent = actuales + " pedido(s) por preparar";
          if (actuales === 0) {
            $("#zona-pedidos").innerHTML = '<div class="vacio">Esperando pedidos...</div>';
          }
        });
      });
    }

    if (nuevos.length > 0) {
      nuevos.forEach((n) => idsPrevios.add(n.id));
    }
    idsPrevios = new Set([...idsPrevios].filter((id) => idsActuales.has(id)));
  } catch (_) {}
}

setInterval(cargar, 3000);
$("#buscador-cocina").addEventListener("input", (e) => {
  textoBusqueda = e.target.value.trim();
  cargar();
});
cargar();
