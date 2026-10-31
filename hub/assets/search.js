(function () {
  var box = document.getElementById("q");
  var results = document.getElementById("results");
  var none = document.getElementById("none");
  if (!box || !results || !none) return;

  var params = new URLSearchParams(location.search);
  var query = params.get("q") || "";
  box.value = query;

  function matches(page, words) {
    var hay = (page.title + " " + page.text).toLowerCase();
    for (var i = 0; i < words.length; i++) {
      if (hay.indexOf(words[i]) === -1) return false;
    }
    return true;
  }

  function pageUrl(page) {
    if (!page.url) return "";
    try {
      var target = new URL(page.url, location.href);
      if (target.hostname === location.hostname) return target.pathname + target.search;
      return target.href;
    } catch (error) {
      return "";
    }
  }

  function label(page) {
    if (!page.url) return "";
    try {
      var target = new URL(page.url);
      return target.host + target.pathname + target.search;
    } catch (error) {
      return "";
    }
  }

  function draw(pages) {
    var words = query.toLowerCase().trim().split(/\s+/).filter(Boolean);
    results.replaceChildren();
    if (!words.length) {
      none.hidden = false;
      none.textContent = "Type something to search the network.";
      results.hidden = true;
      return;
    }
    var found = pages.filter(function (page) { return matches(page, words); });
    none.hidden = found.length > 0;
    none.textContent = "Nothing on the network matches that.";
    results.hidden = found.length === 0;
    found.forEach(function (page) {
      var url = pageUrl(page);
      var row = document.createElement(url ? "a" : "div");
      row.className = "hit";
      if (url) row.href = url;
      var title = document.createElement("strong");
      title.textContent = page.title || url;
      var where = document.createElement("span");
      where.className = "kind";
      where.textContent = label(page) || "This page has no address";
      var body = document.createElement("span");
      body.className = "body";
      body.textContent = page.summary || page.text;
      row.appendChild(title);
      row.appendChild(where);
      row.appendChild(body);
      results.appendChild(row);
    });
  }

  fetch("/assets/catalog.json", { cache: "no-store" })
    .then(function (response) {
      if (!response.ok) throw new Error("catalog");
      return response.json();
    })
    .then(draw)
    .catch(function () {
      none.hidden = false;
      none.textContent = "The network index is not ready.";
    });
})();
