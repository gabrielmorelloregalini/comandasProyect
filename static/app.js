const fmt = (n) => Number(n).toLocaleString("es-AR");

const $ = (sel) => document.querySelector(sel);

let ALIAS = "algo";
let MESERO = null;
let PRODUCTOS = [];
let carrito = new Map(); // clave "pid|aderezos-ids" -> { pid, cantidad, aderezosIds, aderezosNombres }
let tokenPedido = null;
let productoAderezosPendiente = null; // producto del que se estan eligiendo aderezos

function nuevoToken() {
  if (window.crypto && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return "t" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2) + "-" + Math.random().toString(36).slice(2);
}

const vistaLogin = $("#vista-login");
const vistaPedido = $("#vista-pedido");
const vistaPedidos = $("#vista-pedidos");

async function api(url, opciones) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...opciones,
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(txt || "Error");
  }
  return res.json();
}

function renderMeseros(meseros) {
  const caja = $("#lista-meseros");
  caja.innerHTML = "";
  meseros.forEach((c) => {
    const btn = document.createElement("button");
    btn.className = "boton-mesero";
    btn.textContent = c.nombre;
    btn.addEventListener("click", () => elegirMesero(c));
    caja.appendChild(btn);
  });
  if (meseros.length === 0) {
    caja.innerHTML = '<div class="vacio">No hay meseros cargados. Avisale a caja.</div>';
  }
}

function elegirMesero(c) {
  MESERO = c;
  sessionStorage.setItem("scau_mesero", JSON.stringify({ id: c.id, nombre: c.nombre, mesas: c.mesas }));
  $("#mi-nombre").textContent = c.nombre;
  $("#sub-barra").textContent = "Tomando pedidos";
  llenarMesas();
  vistaLogin.classList.add("oculto");
  vistaPedido.classList.remove("oculto");
  $("#input-comprador").value = "";
  carrito.clear();
  renderMenu();
  renderCarrito();
  $("#input-comprador").focus();
}

function llenarMesas() {
  const sel = $("#select-mesa");
  sel.innerHTML = "";
  MESERO.mesas.forEach((m) => {
    const op = document.createElement("option");
    op.value = m.id;
    op.textContent = m.nombre;
    sel.appendChild(op);
  });
  const aviso = $("#aviso-sin-mesas");
  if (MESERO.mesas.length === 0) {
    sel.disabled = true;
    if (aviso) aviso.classList.remove("oculto");
  } else {
    sel.disabled = false;
    if (aviso) aviso.classList.add("oculto");
  }
  actualizarMesa();
}

function actualizarMesa() {
  const sel = $("#select-mesa");
  const op = sel.options[sel.selectedIndex];
  $("#mi-mesa").textContent = op ? op.textContent : "-";
}

// ---------- Carrito por combinaciones ----------
function claveLinea(pid, aderezosIds) {
  const ids = [...aderezosIds].sort().join(",");
  return pid + "|" + ids;
}

function nombreProducto(pid) {
  const p = PRODUCTOS.find((x) => x.id === pid);
  return p ? p.nombre : "?";
}

function agregarUnidad(pid, aderezosIds) {
  const p = PRODUCTOS.find((x) => x.id === pid);
  const ids = [...(aderezosIds || [])];
  const nombres = (p.aderezos || [])
    .filter((a) => ids.includes(a.id))
    .map((a) => a.nombre);
  const clave = claveLinea(pid, ids);
  const linea = carrito.get(clave);
  if (linea) {
    linea.cantidad += 1;
  } else {
    carrito.set(clave, { pid, cantidad: 1, aderezosIds: ids, aderezosNombres: nombres });
  }
}

function lineasDeProducto(pid) {
  return [...carrito.values()].filter((l) => l.pid === pid);
}

function quitarUnidad(pid) {
  const lineas = lineasDeProducto(pid);
  if (lineas.length === 0) return;
  // Prioridad: linea sin aderezos, si no la ultima agregada.
  let objetivo = lineas.find((l) => l.aderezosIds.length === 0) || lineas[lineas.length - 1];
  objetivo.cantidad -= 1;
  if (objetivo.cantidad <= 0) {
    const clave = claveLinea(pid, objetivo.aderezosIds);
    carrito.delete(clave);
  }
}

function cantidadDeProducto(pid) {
  return lineasDeProducto(pid).reduce((acc, l) => acc + l.cantidad, 0);
}

// ---------- Modal aderezos ----------
function abrirModalAderezos(p) {
  productoAderezosPendiente = p;
  $("#modal-aderezos-producto").textContent = p.nombre;
  const caja = $("#modal-aderezos-opciones");
  caja.innerHTML = "";
  p.aderezos.forEach((a) => {
    const label = document.createElement("label");
    label.className = "producto opcion-opcion";
    label.innerHTML = `<span class="info"><span class="nombre"></span></span>
      <input type="checkbox" value="${a.id}">`;
    label.querySelector(".nombre").textContent = a.nombre;
    label.querySelector("input").addEventListener("change", () => {
      $("#chk-sin-aderezo").checked = false;
    });
    caja.appendChild(label);
  });
  $("#chk-sin-aderezo").checked = true;
  $("#chk-sin-aderezo").addEventListener("change", () => {
    if ($("#chk-sin-aderezo").checked) {
      caja.querySelectorAll('input[type="checkbox"]').forEach((cb) => (cb.checked = false));
    }
  });
  $("#modal-aderezos").classList.remove("oculto");
}

function cerrarModalAderezos() {
  productoAderezosPendiente = null;
  $("#modal-aderezos").classList.add("oculto");
}

function confirmarModalAderezos() {
  if (!productoAderezosPendiente) return;
  const p = productoAderezosPendiente;
  const ids = [...$("#modal-aderezos-opciones").querySelectorAll('input[type="checkbox"]:checked')]
    .map((cb) => parseInt(cb.value, 10));
  agregarUnidad(p.id, ids);
  cerrarModalAderezos();
  renderMenu();
  renderCarrito();
}

// ---------- Menu ----------
function renderMenu() {
  const caja = $("#menu-lista");
  caja.innerHTML = "";
  if (PRODUCTOS.length === 0) {
    caja.innerHTML = '<div class="vacio">Todavía no hay productos en el menú.</div>';
    return;
  }
  PRODUCTOS.forEach((p) => {
    const div = document.createElement("div");
    div.className = "producto producto-menu";
    const chips = (p.aderezos || [])
      .map((a) => `<span class="chip-aderezos">${a.nombre}</span>`)
      .join("");
    div.innerHTML = `
      <div class="info">
        <div class="nombre"></div>
        <div class="precio">$ </div>
        ${chips ? `<div class="aderezos-disponibles">${chips}</div>` : ""}
      </div>
      <div class="cant-control">
        <button class="btn btn-borde" data-acc="menos">-</button>
        <span class="n" data-n>0</span>
        <button class="btn btn-primario" data-acc="mas">+</button>
      </div>`;
    div.querySelector(".nombre").textContent = p.nombre;
    div.querySelector(".precio").textContent = "$" + fmt(p.precio);
    const span = div.querySelector("[data-n]");
    span.textContent = cantidadDeProducto(p.id);
    div.querySelector("[data-acc=mas]").addEventListener("click", () => {
      if (p.aderezos && p.aderezos.length > 0) {
        abrirModalAderezos(p);
      } else {
        agregarUnidad(p.id, []);
        renderMenu();
        renderCarrito();
      }
    });
    div.querySelector("[data-acc=menos]").addEventListener("click", () => {
      quitarUnidad(p.id);
      renderMenu();
      renderCarrito();
    });
    caja.appendChild(div);
  });
}

function renderCarrito() {
  const cont = $("#resumen-carrito");
  if (carrito.size === 0) {
    cont.innerHTML = '<div class="vacio" style="padding:10px;">El carrito está vacío.</div>';
  } else {
    let html = "";
    for (const l of carrito.values()) {
      const chips = l.aderezosNombres.length
        ? l.aderezosNombres.map((n) => `<span class="chip-aderezos">${n}</span>`).join(" ")
        : "";
      const subtotal = cantidadProductoPrecio(l);
      html += `
        <div class="carrito-item">
          <span class="nombre">${nombreProducto(l.pid)} x${l.cantidad} ${chips}</span>
          <span class="subtotal">$ ${fmt(subtotal)}</span>
        </div>`;
    }
    const total = [...carrito.values()].reduce((acc, l) => acc + cantidadProductoPrecio(l), 0);
    html += '<div class="total-linea"><span>Total</span><span>$' + fmt(total) + "</span></div>";
    cont.innerHTML = html;
  }
  const comprador = $("#input-comprador").value.trim();
  const tieneMesa = !!$("#select-mesa").value;
  $("#btn-enviar").disabled = carrito.size === 0 || !comprador || !MESERO || !tieneMesa;
}

function cantidadProductoPrecio(l) {
  const p = PRODUCTOS.find((x) => x.id === l.pid);
  return (p ? p.precio : 0) * l.cantidad;
}

function totalCarrito() {
  return [...carrito.values()].reduce((acc, l) => acc + cantidadProductoPrecio(l), 0);
}

// ---------- Modal pago ----------
function abrirModalPago() {
  const comprador = $("#input-comprador").value.trim();
  const mesaId = $("#select-mesa").value;
  if (!comprador || carrito.size === 0 || !MESERO || !mesaId) return;
  document.querySelectorAll('input[name="metodo-pago"]').forEach((r) => (r.checked = false));
  $("#btn-pago-ok").disabled = true;
  $("#modal-pago").classList.remove("oculto");
}

function cerrarModalPago() {
  $("#modal-pago").classList.add("oculto");
}

async function enviarPedido(metodoPago) {
  const comprador = $("#input-comprador").value.trim();
  const mesaId = parseInt($("#select-mesa").value, 10);
  if (!comprador || carrito.size === 0) return;
  if (!tokenPedido) tokenPedido = nuevoToken();
  const btn = $("#btn-enviar");
  btn.disabled = true;
  btn.textContent = "Enviando...";
  try {
    const items = [...carrito.values()].map((l) => ({
      producto_id: l.pid,
      cantidad: l.cantidad,
      aderezos: l.aderezosIds,
    }));
    const resp = await api("/api/pedidos", {
      method: "POST",
      body: JSON.stringify({ mesero_id: MESERO.id, mesa_id: mesaId, comprador, items, token: tokenPedido, metodo_pago: metodoPago }),
    });
    tokenPedido = null;
    $("#modal-numero").textContent = resp.numero;
    $("#modal-total").textContent = "$" + fmt(resp.total);
    $("#modal-alias").textContent = ALIAS;
    cerrarModalPago();
    $("#modal-confirmar").classList.remove("oculto");
    carrito.clear();
    renderMenu();
    renderCarrito();
  } catch (e) {
    alert("No se pudo enviar el pedido: " + e.message);
  } finally {
    btn.textContent = "Confirmar pedido";
  }
}

function renderMisPedidos(pedidos) {
  const caja = $("#mis-pedidos-lista");
  if (pedidos.length === 0) {
    caja.innerHTML = '<div class="vacio">Todavía no tomaste pedidos.</div>';
    return;
  }
  caja.innerHTML = "";
  pedidos.forEach((p) => {
    const div = document.createElement("div");
    div.className = "mis-pedidos-item";
    const estado = p.estado === "cobrado"
      ? '<span class="badge cobrado">Cobrado</span>'
      : p.estado === "cancelado"
      ? '<span class="badge cancelado">Cancelado</span>'
      : '<span class="badge pendiente">Pendiente</span>';
    div.innerHTML = `
      <div class="izq">
        <span class="num"></span>
        <div>
          <div class="detalle"></div>
          <div class="total">$ </div>
        </div>
      </div>
      ${estado}`;
    div.querySelector(".num").textContent = p.numero;
    div.querySelector(".detalle").textContent = p.comprador + " - " + p.mesa;
    div.querySelector(".total").textContent = "$" + fmt(p.total);
    caja.appendChild(div);
  });
}

async function actualizarMisPedidos() {
  if (!MESERO || vistaPedidos.classList.contains("oculto")) return;
  try {
    const pedidos = await api("/api/pedidos?mesero_id=" + MESERO.id);
    renderMisPedidos(pedidos);
  } catch (_) {}
}

function irAPedidos() {
  $("#modal-confirmar").classList.add("oculto");
  vistaPedido.classList.add("oculto");
  vistaPedidos.classList.remove("oculto");
  actualizarMisPedidos();
}

function volverAPedido() {
  vistaPedidos.classList.add("oculto");
  vistaPedido.classList.remove("oculto");
  $("#input-comprador").value = "";
  $("#input-comprador").focus();
}

async function init() {
  try {
    const config = await api("/api/config");
    ALIAS = config.alias;
  } catch (_) {}
  try {
    PRODUCTOS = await api("/api/productos");
  } catch (_) {}
  try {
    const meseros = await api("/api/meseros");
    renderMeseros(meseros);
  } catch (_) {}

  const guardado = sessionStorage.getItem("scau_mesero");
  if (guardado) {
    try {
      const c = JSON.parse(guardado);
      if (c && c.id && c.nombre && c.mesas) {
        elegirMesero(c);
      }
    } catch (_) {}
  }

  $("#input-comprador").addEventListener("input", renderCarrito);
  $("#select-mesa").addEventListener("change", actualizarMesa);
  $("#btn-enviar").addEventListener("click", abrirModalPago);
  $("#btn-cambiar").addEventListener("click", () => {
    MESERO = null;
    sessionStorage.removeItem("scau_mesero");
    vistaPedido.classList.add("oculto");
    vistaLogin.classList.remove("oculto");
  });
  $("#btn-modal-ok").addEventListener("click", () => {
    location.reload();
  });
  $("#btn-nuevo-pedido").addEventListener("click", volverAPedido);
  $("#btn-mis-pedidos").addEventListener("click", irAPedidos);

  // Modal aderezos
  $("#btn-aderezos-ok").addEventListener("click", confirmarModalAderezos);
  $("#btn-aderezos-cancelar").addEventListener("click", cerrarModalAderezos);
  $("#chk-sin-aderezo").addEventListener("change", () => {
    if ($("#chk-sin-aderezo").checked) {
      $("#modal-aderezos-opciones").querySelectorAll('input[type="checkbox"]').forEach((cb) => (cb.checked = false));
    }
  });

  // Modal pago
  document.querySelectorAll('input[name="metodo-pago"]').forEach((r) => {
    r.addEventListener("change", () => {
      $("#btn-pago-ok").disabled = false;
    });
  });
  $("#btn-pago-ok").addEventListener("click", () => {
    const elegido = document.querySelector('input[name="metodo-pago"]:checked');
    if (elegido) enviarPedido(elegido.value);
  });
  $("#btn-pago-cancelar").addEventListener("click", cerrarModalPago);

  setInterval(actualizarMisPedidos, 5000);
}

init();