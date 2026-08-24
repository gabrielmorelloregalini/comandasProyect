const fmt = (n) => Number(n).toLocaleString("es-AR");
const $ = (sel) => document.querySelector(sel);

let ALIAS = "";
let filtroComandas = "pendiente";
let textoBusqueda = "";
let abiertas = new Set(); // ids de comandas desplegadas
let editandoProducto = null;
let editandoMesa = null;
let editandoMesero = null;

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

// ---------- Pestanas ----------
function cambiarPestana(nombre) {
  document.querySelectorAll(".pestana").forEach((b) => {
    b.classList.toggle("btn-primario", b.dataset.pestana === nombre);
  });
  ["comandas", "ventas", "productos", "aderezos", "mesas", "meseros", "alias"].forEach((p) => {
    $("#pestana-" + p).classList.toggle("oculto", p !== nombre);
  });
  if (nombre === "comandas") cargarComandas();
  if (nombre === "ventas") cargarVentas();
  if (nombre === "productos") cargarProductos();
  if (nombre === "aderezos") cargarAderezos();
  if (nombre === "mesas") cargarMesas();
  if (nombre === "meseros") { cargarMeseros(); cargarMesasParaMeseros(); }
  if (nombre === "alias") cargarAlias();
}

document.querySelectorAll(".pestana").forEach((b) => {
  b.addEventListener("click", () => cambiarPestana(b.dataset.pestana));
});
document.querySelectorAll(".filtro").forEach((b) => {
  b.addEventListener("click", () => {
    filtroComandas = b.dataset.filtro;
    document.querySelectorAll(".filtro").forEach((f) => f.classList.toggle("btn-primario", f === b));
    cargarComandas();
  });
});

// ---------- Comandas ----------
function chipsAderezos(lista) {
  if (!lista || lista.length === 0) return "";
  return lista.map((a) => `<span class="chip-aderezos">${a}</span>`).join(" ");
}

function tarjetaComanda(p) {
  const items = p.items.map((i) => `
    <div class="comanda-item-lista">
      <span><span class="cant">${i.cantidad} x</span>${i.nombre} ${chipsAderezos(i.aderezos)}</span>
      <span>$ ${fmt(i.precio * i.cantidad)}</span>
    </div>`).join("");

  const badge = p.estado === "cobrado"
    ? '<span class="badge cobrado">Cobrado</span>'
    : p.estado === "cancelado"
    ? '<span class="badge cancelado">Cancelado</span>'
    : '<span class="badge pendiente">Pendiente</span>';

  const metodo = p.metodo_pago
    ? `<span class="badge metodo ${p.metodo_pago}">${p.metodo_pago === "efectivo" ? "Efectivo" : "Transferencia"}</span>`
    : "";

  const btnCobrar = p.estado === "pendiente"
    ? `<div class="fila-accion"><button class="btn btn-primario btn-cobrar" data-id="${p.id}">Marcar como cobrado</button></div>`
    : "";

  const btnCancelar = (p.estado === "pendiente" || p.estado === "cobrado")
    ? `<button class="btn btn-rojo btn-cancelar" data-id="${p.id}">Cancelar comanda</button>`
    : "";

  const acciones = (btnCobrar || btnCancelar)
    ? `<div class="fila-accion">${btnCancelar}${btnCobrar}</div>`
    : "";

  const abierta = abiertas.has(p.id) ? "open" : "";

  return `
    <details class="tarjeta comanda-detalle ${p.estado === "cobrado" ? "cobrada" : p.estado === "cancelado" ? "cancelada" : ""}" ${abierta} data-id="${p.id}">
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
        <div class="comanda-total">Total: $ ${fmt(p.total)}</div>
        <div class="alias-box">
          <div class="etiqueta">Alias Mercado Pago</div>
          <div class="valor">${ALIAS}</div>
        </div>
        ${acciones}
      </div>
    </details>`;
}

function filtrarComanda(p) {
  if (filtroComandas !== "todas" && p.estado !== filtroComandas) return false;
  const q = textoBusqueda.toLowerCase();
  if (!q) return true;
  return (p.numero + " " + p.mesa + " " + p.comprador + " " + p.mesero).toLowerCase().includes(q);
}

async function cargarComandas() {
  try {
    const pedidos = await api("/api/pedidos");
    const lista = $("#lista-comandas");
    const filtrados = pedidos.filter(filtrarComanda);
    if (filtrados.length === 0) {
      lista.innerHTML = '<div class="vacio">No hay comandas.</div>';
      return;
    }
    lista.innerHTML = filtrados.map(tarjetaComanda).join("");
    lista.querySelectorAll(".comanda-detalle").forEach((d) => {
      const id = Number(d.dataset.id);
      d.addEventListener("toggle", () => {
        if (d.open) abiertas.add(id);
        else abiertas.delete(id);
      });
    });
    lista.querySelectorAll(".btn-cobrar").forEach((b) => {
      b.addEventListener("click", async () => {
        try {
          await api("/api/pedidos/" + b.dataset.id + "/cobrar", { method: "POST" });
          cargarComandas();
        } catch (e) {
          alert("Error: " + e.message);
        }
      });
    });
    lista.querySelectorAll(".btn-cancelar").forEach((b) => {
      b.addEventListener("click", async () => {
        if (!confirm("¿Cancelar esta comanda? Quedará registrada como cancelada y no sumará a las ventas.")) return;
        try {
          await api("/api/pedidos/" + b.dataset.id + "/cancelar", { method: "POST" });
          cargarComandas();
        } catch (e) {
          alert("Error: " + e.message);
        }
      });
    });
  } catch (e) {
    $("#lista-comandas").innerHTML = '<div class="vacio">Error al cargar: ' + e.message + "</div>";
  }
}

// ---------- Productos ----------
let aderezosGlobal = []; // lista global de aderezos {id, nombre}

function renderProductos(productos) {
  const tb = $("#tabla-productos");
  tb.innerHTML = productos.map((p) => `
    <tr>
      <td>${p.nombre}</td>
      <td>$ ${fmt(p.precio)}</td>
      <td>${chipsAderezos((p.aderezos || []).map((a) => a.nombre))}</td>
      <td class="acciones">
        <button class="btn btn-azul prod-editar" data-id="${p.id}">Editar</button>
        <button class="btn btn-rojo prod-borrar" data-id="${p.id}">Eliminar</button>
      </td>
    </tr>`).join("") || '<tr><td colspan="4">Sin productos.</td></tr>';

  tb.querySelectorAll(".prod-editar").forEach((b) => {
    b.addEventListener("click", () => editarProducto(Number(b.dataset.id)));
  });
  tb.querySelectorAll(".prod-borrar").forEach((b) => {
    b.addEventListener("click", async () => {
      if (confirm("¿Eliminar este producto del menú?")) {
        await api("/api/productos/" + b.dataset.id, { method: "DELETE" });
        cargarProductos();
      }
    });
  });
}

function renderOpcionesAderezosProducto(seleccionadas) {
  const caja = $("#prod-aderezos-opciones");
  caja.innerHTML = "";
  if (aderezosGlobal.length === 0) {
    caja.innerHTML = '<div class="aviso">Primero creá aderezos en la pestaña Aderezos.</div>';
    return;
  }
  aderezosGlobal.forEach((a) => {
    const label = document.createElement("label");
    label.className = "producto";
    label.style.cursor = "pointer";
    label.innerHTML = `<span class="info"><span class="nombre">${a.nombre}</span></span>
      <input type="checkbox" value="${a.id}">`;
    label.querySelector("input").checked = seleccionadas.has(a.id);
    caja.appendChild(label);
  });
}

function aderezosSeleccionadosProducto() {
  return [...$("#prod-aderezos-opciones").querySelectorAll("input:checked")].map((c) => parseInt(c.value, 10));
}

async function cargarProductos() {
  try {
    renderProductos(await api("/api/productos"));
  } catch (e) { alert("Error: " + e.message); }
}

async function cargarAderezosGlobal() {
  try {
    aderezosGlobal = await api("/api/aderezos");
  } catch (e) { alert("Error: " + e.message); }
}

function editarProducto(id) {
  api("/api/productos").then((prods) => {
    const p = prods.find((x) => x.id === id);
    if (!p) return;
    editandoProducto = id;
    $("#prod-nombre").value = p.nombre;
    $("#prod-precio").value = p.precio;
    renderOpcionesAderezosProducto(new Set((p.aderezos || []).map((a) => a.id)));
    $("#prod-guardar").textContent = "Guardar cambios";
    $("#prod-cancelar").classList.remove("oculto");
    $("#prod-nombre").focus();
  });
}

$("#form-producto").addEventListener("submit", async (e) => {
  e.preventDefault();
  const nombre = $("#prod-nombre").value.trim();
  const precio = parseInt($("#prod-precio").value, 10);
  const aderezos = aderezosSeleccionadosProducto();
  if (!nombre || isNaN(precio)) return;
  try {
    if (editandoProducto !== null) {
      await api("/api/productos/" + editandoProducto, {
        method: "PUT",
        body: JSON.stringify({ nombre, precio, aderezos }),
      });
    } else {
      await api("/api/productos", {
        method: "POST",
        body: JSON.stringify({ nombre, precio, aderezos }),
      });
    }
    editandoProducto = null;
    $("#prod-guardar").textContent = "Agregar producto";
    $("#prod-cancelar").classList.add("oculto");
    renderOpcionesAderezosProducto(new Set());
    e.target.reset();
    cargarProductos();
  } catch (err) { alert("Error: " + err.message); }
});

$("#prod-cancelar").addEventListener("click", () => {
  editandoProducto = null;
  $("#prod-guardar").textContent = "Agregar producto";
  $("#prod-cancelar").classList.add("oculto");
  renderOpcionesAderezosProducto(new Set());
  $("#form-producto").reset();
});

// ---------- Aderezos ----------
let editandoAderezo = null;

function renderAderezos(aderezos) {
  const tb = $("#tabla-aderezos");
  tb.innerHTML = aderezos.map((a) => `
    <tr>
      <td>${a.nombre}</td>
      <td class="acciones">
        <button class="btn btn-azul aderezo-editar" data-id="${a.id}">Editar</button>
        <button class="btn btn-rojo aderezo-borrar" data-id="${a.id}">Eliminar</button>
      </td>
    </tr>`).join("") || '<tr><td colspan="2">Sin aderezos.</td></tr>';

  tb.querySelectorAll(".aderezo-editar").forEach((b) => {
    b.addEventListener("click", () => editarAderezo(Number(b.dataset.id)));
  });
  tb.querySelectorAll(".aderezo-borrar").forEach((b) => {
    b.addEventListener("click", async () => {
      if (confirm("¿Eliminar este aderezo? Se quitará de los productos que lo usen.")) {
        await api("/api/aderezos/" + b.dataset.id, { method: "DELETE" });
        cargarAderezos();
        cargarAderezosGlobal();
      }
    });
  });
}

async function cargarAderezos() {
  try {
    renderAderezos(await api("/api/aderezos"));
  } catch (e) { alert("Error: " + e.message); }
}

function editarAderezo(id) {
  api("/api/aderezos").then((aderezos) => {
    const a = aderezos.find((x) => x.id === id);
    if (!a) return;
    editandoAderezo = id;
    $("#aderezo-nombre").value = a.nombre;
    $("#aderezo-guardar").textContent = "Guardar cambios";
    $("#aderezo-cancelar").classList.remove("oculto");
    $("#aderezo-nombre").focus();
  });
}

$("#form-aderezo").addEventListener("submit", async (e) => {
  e.preventDefault();
  const nombre = $("#aderezo-nombre").value.trim();
  if (!nombre) return;
  try {
    if (editandoAderezo !== null) {
      await api("/api/aderezos/" + editandoAderezo, { method: "PUT", body: JSON.stringify({ nombre }) });
    } else {
      await api("/api/aderezos", { method: "POST", body: JSON.stringify({ nombre }) });
    }
    editandoAderezo = null;
    $("#aderezo-guardar").textContent = "Agregar aderezo";
    $("#aderezo-cancelar").classList.add("oculto");
    e.target.reset();
    cargarAderezos();
    cargarAderezosGlobal();
  } catch (err) { alert("Error: " + err.message); }
});

$("#aderezo-cancelar").addEventListener("click", () => {
  editandoAderezo = null;
  $("#aderezo-guardar").textContent = "Agregar aderezo";
  $("#aderezo-cancelar").classList.add("oculto");
  $("#form-aderezo").reset();
});

// ---------- Ventas ----------
function renderVentas(v) {
  $("#venta-efectivo").textContent = "$ " + fmt(v.efectivo || 0);
  $("#venta-transferencia").textContent = "$ " + fmt(v.transferencia || 0);
  $("#venta-total").textContent = "$ " + fmt(v.total || 0);
  const aviso = $("#venta-sin-registrar");
  const sin = Number(v.sin_registrar || 0);
  if (sin > 0) {
    aviso.textContent = "Hay $ " + fmt(sin) + " cobrados sin método registrado (pedidos viejos); el total los incluye.";
    aviso.classList.remove("oculto");
  } else {
    aviso.classList.add("oculto");
  }
}

async function cargarVentas() {
  try {
    renderVentas(await api("/api/ventas"));
  } catch (_) {}
}

// ---------- Mesas ----------
function renderMesas(mesas) {
  const tb = $("#tabla-mesas");
  tb.innerHTML = mesas.map((m) => `
    <tr>
      <td>${m.nombre}</td>
      <td class="acciones">
        <button class="btn btn-azul mesa-editar" data-id="${m.id}">Editar</button>
        <button class="btn btn-rojo mesa-borrar" data-id="${m.id}">Eliminar</button>
      </td>
    </tr>`).join("") || '<tr><td colspan="2">Sin mesas.</td></tr>';

  tb.querySelectorAll(".mesa-editar").forEach((b) => {
    b.addEventListener("click", () => editarMesa(Number(b.dataset.id)));
  });
  tb.querySelectorAll(".mesa-borrar").forEach((b) => {
    b.addEventListener("click", async () => {
      if (confirm("¿Eliminar esta mesa?")) {
        await api("/api/mesas/" + b.dataset.id, { method: "DELETE" });
        cargarMesas();
      }
    });
  });
}

async function cargarMesas() {
  try {
    renderMesas(await api("/api/mesas"));
  } catch (e) { alert("Error: " + e.message); }
}

function editarMesa(id) {
  api("/api/mesas").then((mesas) => {
    const m = mesas.find((x) => x.id === id);
    if (!m) return;
    editandoMesa = id;
    $("#mesa-nombre").value = m.nombre;
    $("#mesa-guardar").textContent = "Guardar cambios";
    $("#mesa-cancelar").classList.remove("oculto");
    $("#mesa-nombre").focus();
  });
}

$("#form-mesa").addEventListener("submit", async (e) => {
  e.preventDefault();
  const nombre = $("#mesa-nombre").value.trim();
  if (!nombre) return;
  try {
    if (editandoMesa !== null) {
      await api("/api/mesas/" + editandoMesa, { method: "PUT", body: JSON.stringify({ nombre }) });
    } else {
      await api("/api/mesas", { method: "POST", body: JSON.stringify({ nombre }) });
    }
    editandoMesa = null;
    $("#mesa-guardar").textContent = "Agregar mesa";
    $("#mesa-cancelar").classList.add("oculto");
    e.target.reset();
    cargarMesas();
  } catch (err) { alert("Error: " + err.message); }
});

$("#mesa-cancelar").addEventListener("click", () => {
  editandoMesa = null;
  $("#mesa-guardar").textContent = "Agregar mesa";
  $("#mesa-cancelar").classList.add("oculto");
  $("#form-mesa").reset();
});

// ---------- Meseros ----------
function renderOpcionesMesas(mesas, seleccionadas) {
  const caja = $("#mesero-mesas-opciones");
  caja.innerHTML = "";
  if (mesas.length === 0) {
    caja.innerHTML = '<div class="aviso">Primero creá mesas en la pestaña Mesas.</div>';
    return;
  }
  mesas.forEach((m) => {
    const label = document.createElement("label");
    label.className = "producto";
    label.style.cursor = "pointer";
    label.innerHTML = `<span class="info"><span class="nombre">${m.nombre}</span></span>
      <input type="checkbox" value="${m.id}">`;
    label.querySelector("input").checked = seleccionadas.has(m.id);
    caja.appendChild(label);
  });
}

function mesasSeleccionadas() {
  return [...$("#mesero-mesas-opciones").querySelectorAll("input:checked")].map((c) => parseInt(c.value, 10));
}

function renderMeseros(meseros) {
  const tb = $("#tabla-meseros");
  tb.innerHTML = meseros.map((c) => `
    <tr>
      <td>${c.nombre}</td>
      <td>${c.mesas.map((m) => m.nombre).join(", ") || "-"}</td>
      <td class="acciones">
        <button class="btn btn-azul mesero-editar" data-id="${c.id}">Editar</button>
        <button class="btn btn-rojo mesero-borrar" data-id="${c.id}">Eliminar</button>
      </td>
    </tr>`).join("") || '<tr><td colspan="3">Sin meseros.</td></tr>';

  tb.querySelectorAll(".mesero-editar").forEach((b) => {
    b.addEventListener("click", () => editarMesero(Number(b.dataset.id)));
  });
  tb.querySelectorAll(".mesero-borrar").forEach((b) => {
    b.addEventListener("click", async () => {
      if (confirm("¿Eliminar este mesero?")) {
        await api("/api/meseros/" + b.dataset.id, { method: "DELETE" });
        cargarMeseros();
      }
    });
  });
}

async function cargarMeseros() {
  try {
    renderMeseros(await api("/api/meseros"));
  } catch (e) { alert("Error: " + e.message); }
}

function editarMesero(id) {
  api("/api/meseros").then((meseros) => {
    const c = meseros.find((x) => x.id === id);
    if (!c) return;
    editandoMesero = id;
    $("#mesero-nombre").value = c.nombre;
    renderOpcionesMesas(mesasGlobal, new Set(c.mesas.map((m) => m.id)));
    $("#mesero-guardar").textContent = "Guardar cambios";
    $("#mesero-cancelar").classList.remove("oculto");
    $("#mesero-nombre").focus();
  });
}

let mesasGlobal = [];

async function cargarMesasParaMeseros() {
  try {
    mesasGlobal = await api("/api/mesas");
    renderOpcionesMesas(mesasGlobal, new Set());
  } catch (e) { alert("Error: " + e.message); }
}

$("#form-mesero").addEventListener("submit", async (e) => {
  e.preventDefault();
  const nombre = $("#mesero-nombre").value.trim();
  const mesas = mesasSeleccionadas();
  if (!nombre) return;
  try {
    if (editandoMesero !== null) {
      await api("/api/meseros/" + editandoMesero, { method: "PUT", body: JSON.stringify({ nombre, mesas }) });
    } else {
      await api("/api/meseros", { method: "POST", body: JSON.stringify({ nombre, mesas }) });
    }
    editandoMesero = null;
    $("#mesero-guardar").textContent = "Agregar mesero";
    $("#mesero-cancelar").classList.add("oculto");
    e.target.reset();
    renderOpcionesMesas(mesasGlobal, new Set());
    cargarMeseros();
  } catch (err) { alert("Error: " + err.message); }
});

$("#mesero-cancelar").addEventListener("click", () => {
  editandoMesero = null;
  $("#mesero-guardar").textContent = "Agregar mesero";
  $("#mesero-cancelar").classList.add("oculto");
  $("#form-mesero").reset();
  renderOpcionesMesas(mesasGlobal, new Set());
});

// ---------- Alias Mercado Pago ----------
async function cargarAlias() {
  try {
    const cfg = await api("/api/config");
    ALIAS = cfg.alias || "";
    $("#alias-mp").value = ALIAS;
  } catch (e) { alert("Error: " + e.message); }
}

$("#form-alias").addEventListener("submit", async (e) => {
  e.preventDefault();
  const alias = $("#alias-mp").value.trim();
  if (!alias) return;
  const btn = $("#alias-guardar");
  try {
    await api("/api/config", { method: "PUT", body: JSON.stringify({ alias }) });
    ALIAS = alias;
    btn.textContent = "Guardado";
    setTimeout(() => { btn.textContent = "Guardar alias"; }, 1500);
  } catch (err) { alert("Error: " + err.message); }
});

// ---------- Init ----------
async function init() {
  try {
    ALIAS = (await api("/api/config")).alias;
  } catch (_) {}
  cargarComandas();
  cargarMesasParaMeseros();
  cargarAderezosGlobal();
  $("#buscador-comandas").addEventListener("input", (e) => {
    textoBusqueda = e.target.value.trim();
    cargarComandas();
  });
  setInterval(() => {
    if (!$("#pestana-comandas").classList.contains("oculto")) cargarComandas();
    if (!$("#pestana-ventas").classList.contains("oculto")) cargarVentas();
  }, 3000);
}

init();
