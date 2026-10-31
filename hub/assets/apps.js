(function () {
  var onHub = location.hostname === "hub.nm" || location.hostname === "hub.nm-mesh.daddar.io";
  var host = location.protocol + "//" + location.hostname;
  var links = {
    "app-search": "/",
    "mesh-directory": onHub ? "/directory/" : host + ":8090/directory/",
    "app-square": onHub ? host.replace("//hub.", "//square.") + "/" : host + ":8094/"
  };
  Object.keys(links).forEach(function (id) {
    var link = document.getElementById(id);
    if (link) link.href = links[id];
  });

  var button = document.getElementById("apps-button");
  var menu = document.getElementById("apps-menu");
  if (!button || !menu) return;

  function place() {
    var box = button.getBoundingClientRect();
    menu.style.top = (box.bottom + 8) + "px";
    menu.style.left = "auto";
    menu.style.right = Math.max(8, window.innerWidth - box.right) + "px";
  }

  function close() {
    menu.hidden = true;
    button.setAttribute("aria-expanded", "false");
  }

  button.addEventListener("click", function (event) {
    event.stopPropagation();
    var open = menu.hidden;
    if (open) {
      document.dispatchEvent(new CustomEvent("mesh-open", { detail: "apps" }));
      place();
    }
    menu.hidden = !open;
    button.setAttribute("aria-expanded", open ? "true" : "false");
  });

  document.addEventListener("mesh-open", function (event) {
    if (event.detail !== "apps") close();
  });

  document.addEventListener("click", function (event) {
    if (!menu.contains(event.target)) close();
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") close();
  });
})();
