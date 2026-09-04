const fmt = (n) => Number(n).toLocaleString("es-AR");
const $ = (sel) => document.querySelector(sel);

let idsPrevios = new Set();
let abiertas = new Set();
let textoBusqueda = "";
let pestanaCocina = "preparar";

async function cambiarEstadoPedido(id, estado) {
  const res = await fetch("/api/pedidos/" + id + "/estado", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ estado }),
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(txt || "Error al cambiar estado");
  }
}

function chipsAderezos(lista) {
  if (!lista || lista.length === 0) return "";
  return lista.map((a) => `<span class="chip-aderezos">${a}</span>`).join(" ");
}

function tarjetaCocina(p, esNuevo) {
  const items = p.items.map((i) => `
    <div class="comanda-item-lista">
      <span><span class="cant">${i.cantidad} x</span>${i.nombre} ${chipsAderezos(i.aderezos)}</span>
    </div>`).join("");
  const badge = '<span class="badge cobrado">Cobrado</span>';
  const metodo = p.metodo_pago ? `<span class="badge metodo ${p.metodo_pago}">${p.metodo_pago === "efectivo" ? "Efectivo" : "Transferencia"}</span>` : "";
  const abierta = abiertas.has(p.id) ? "open" : "";
  const esNuevoCls = esNuevo ? " nuevo" : "";
  return `
    <details class="tarjeta comanda-detalle cocina cobrada${esNuevoCls}" ${abierta} data-id="${p.id}">
      <summary>
        <span class="comanda-numero">${p.numero}</span>
        <span class="comanda-meta">
          <span><b>Mesa:</b> ${p.mesa}</span>
          <span><b>Comprador:</b> ${p.comprador}</span>
          <span><b>Mesero:</b> ${p.mesero}</span>
          <span><b>Hora:</b> ${p.creado_en.slice(11, 16)}</span>
        </span>
        ${metodo}
        ${badge}
        <span class="chevron">▾</span>
      </summary>
      <div class="comanda-contenido">
        <div class="comanda-items">${items}</div>
        <div class="fila-accion"><button class="btn btn-naranja ocultar" data-id="${p.id}">Finalizar</button></div>
      </div>
    </details>`;
}

function tarjetaFinalizado(p) {
  const items = p.items.map((i) => `
    <div class="comanda-item-lista">
      <span><span class="cant">${i.cantidad} x</span>${i.nombre} ${chipsAderezos(i.aderezos)}</span>
    </div>`).join("");
  const metodo = p.metodo_pago ? `<span class="badge metodo ${p.metodo_pago}">${p.metodo_pago === "efectivo" ? "Efectivo" : "Transferencia"}</span>` : "";
  const abierta = abiertas.has(p.id) ? "open" : "";
  return `
    <details class="tarjeta comanda-detalle cocina finalizada" ${abierta} data-id="${p.id}">
      <summary>
        <span class="comanda-numero">${p.numero}</span>
        <span class="comanda-meta">
          <span><b>Mesa:</b> ${p.mesa}</span>
          <span><b>Comprador:</b> ${p.comprador}</span>
          <span><b>Mesero:</b> ${p.mesero}</span>
          <span><b>Hora:</b> ${p.creado_en.slice(11, 16)}</span>
        </span>
        ${metodo}
        <span class="badge finalizado">Finalizado</span>
        <span class="chevron">▾</span>
      </summary>
      <div class="comanda-contenido">
        <div class="comanda-items">${items}</div>
        <div class="fila-accion"><button class="btn btn-borde revertir" data-id="${p.id}">→ Cobrado</button></div>
      </div>
    </details>`;
}

function filtrarComanda(p) {
  const q = textoBusqueda.toLowerCase();
  if (!q) return true;
  return (p.numero + " " + p.mesa + " " + p.comprador + " " + p.mesero).toLowerCase().includes(q);
}

function cambiarPestanaCocina(nombre) {
  document.querySelectorAll(".pestana").forEach((b) => {
    b.classList.toggle("btn-primario", b.dataset.pestana === nombre);
  });
  document.getElementById("pestana-preparar").classList.toggle("oculto", nombre !== "preparar");
  document.getElementById("pestana-finalizados-cocina").classList.toggle("oculto", nombre !== "finalizados");
  pestanaCocina = nombre;
  if (nombre === "preparar") cargar();
  else cargarFinalizados();
}

document.querySelectorAll(".pestana").forEach((b) => {
  b.addEventListener("click", () => cambiarPestanaCocina(b.dataset.pestana));
});

async function cargar() {
  try {
    const res = await fetch("/api/pedidos?estado=cobrado&limit=500");
    const pedidos = await res.json();
    const porPreparar = pedidos
      .filter((p) => p.estado === "cobrado")
      .sort((a, b) => b.id - a.id);
    const cobrados = porPreparar.filter(filtrarComanda);
    const resaltarBusqueda = (textoBusqueda.length > 0) && porPreparar.length !== cobrados.length;

    if (pestanaCocina === "preparar") {
      if (resaltarBusqueda) {
        $("#contador").textContent = cobrados.length + " coincidencia(s) de " + porPreparar.length + " pedido(s) por preparar";
      } else {
        $("#contador").textContent = porPreparar.length + " pedido(s) por preparar";
      }
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
      zona.querySelectorAll(".comanda-detalle").forEach((d) => {
        const id = Number(d.dataset.id);
        d.addEventListener("toggle", () => {
          if (d.open) abiertas.add(id);
          else abiertas.delete(id);
        });
      });
      zona.querySelectorAll(".ocultar").forEach((btn) => {
        btn.addEventListener("click", async () => {
          btn.disabled = true;
          try {
            await cambiarEstadoPedido(btn.dataset.id, "finalizado");
            btn.closest(".tarjeta").remove();
            const actuales = document.querySelectorAll("#zona-pedidos .tarjeta").length;
            if (pestanaCocina === "preparar") {
              $("#contador").textContent = actuales + " pedido(s) por preparar";
            }
            if (actuales === 0) {
              $("#zona-pedidos").innerHTML = '<div class="vacio">Esperando pedidos...</div>';
            }
          } catch (e) {
            alert("Error: " + e.message);
            btn.disabled = false;
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

async function cargarFinalizados() {
  try {
    const res = await fetch("/api/pedidos?estado=finalizado&limit=500");
    const pedidos = await res.json();
    const filtrados = pedidos.filter(filtrarComanda).sort((a,b)=>b.id-a.id);
    const zona = $("#zona-finalizados");
    if (filtrados.length === 0) {
      zona.innerHTML = '<div class="vacio">No hay pedidos finalizados.</div>';
      return;
    }
    zona.innerHTML = filtrados.map(tarjetaFinalizado).join("");
    zona.querySelectorAll(".comanda-detalle").forEach((d) => {
      const id = Number(d.dataset.id);
      d.addEventListener("toggle", () => {
        if (d.open) abiertas.add(id);
        else abiertas.delete(id);
      });
    });
    zona.querySelectorAll(".revertir").forEach((btn) => {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          await cambiarEstadoPedido(btn.dataset.id, "cobrado");
          cargarFinalizados();
          cargar();
        } catch (e) {
          alert("Error: " + e.message);
          btn.disabled = false;
        }
      });
    });
  } catch (_) {}
}

setInterval(() => {
  if (pestanaCocina === "preparar") cargar();
  else cargarFinalizados();
}, 3000);
$("#buscador-cocina").addEventListener("input", (e) => {
  textoBusqueda = e.target.value.trim();
  if (pestanaCocina === "preparar") cargar();
  else cargarFinalizados();
});
cargar();
