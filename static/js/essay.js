// Essay workspace: word counter, unsaved-changes warning, and select-text-to-comment.
(function () {
  "use strict";

  // ---- Editor: live word / character count and leave-page warning
  document.querySelectorAll("textarea.essay-editor").forEach(function (area) {
    var out = document.getElementById("essay-count");
    var wordLimit = parseInt(area.dataset.wordLimit || "0", 10);
    var charLimit = parseInt(area.dataset.charLimit || "0", 10);
    var dirty = false;

    function update() {
      var text = area.value.replace(/\r\n/g, "\n");
      var trimmed = text.trim();
      var words = trimmed ? trimmed.split(/\s+/).length : 0;
      var chars = text.length;
      if (out) {
        out.textContent = words + (wordLimit ? " / " + wordLimit : "") + " words · " +
          chars + (charLimit ? " / " + charLimit : "") + " characters";
        out.classList.toggle("over-limit", (wordLimit && words > wordLimit) || (charLimit && chars > charLimit));
      }
    }
    area.addEventListener("input", function () { dirty = true; update(); });
    area.form.addEventListener("submit", function () { dirty = false; });
    window.addEventListener("beforeunload", function (e) {
      if (dirty) { e.preventDefault(); e.returnValue = ""; }
    });
    update();
  });

  // ---- Reader: select a passage to anchor a comment to it
  var text = document.getElementById("essay-text");
  var form = document.getElementById("comment-form");
  if (text && form) {
    var quote = form.querySelector("[name=quote]");
    var start = form.querySelector("[name=start]");
    var end = form.querySelector("[name=end]");
    var box = document.getElementById("comment-anchor");
    var label = document.getElementById("comment-quote");

    function offsetOf(node, offset) {
      var range = document.createRange();
      range.setStart(text, 0);
      range.setEnd(node, offset);
      return range.toString().length;
    }

    function clear() {
      quote.value = ""; start.value = ""; end.value = "";
      box.hidden = true;
    }

    document.addEventListener("selectionchange", function () {
      var sel = window.getSelection();
      if (!sel || !sel.rangeCount) return;
      var r = sel.getRangeAt(0);
      // Ignore selections outside the essay (e.g. the cursor moving into the comment box).
      if (r.collapsed || !text.contains(r.startContainer) || !text.contains(r.endContainer)) return;
      var a = offsetOf(r.startContainer, r.startOffset);
      var b = offsetOf(r.endContainer, r.endOffset);
      if (b <= a) return;
      start.value = a; end.value = b;
      quote.value = text.textContent.slice(a, b);
      label.textContent = "“" + quote.value.slice(0, 200) + (quote.value.length > 200 ? "…" : "") + "”";
      box.hidden = false;
    });

    var clearBtn = document.getElementById("comment-clear");
    if (clearBtn) clearBtn.addEventListener("click", clear);
  }

  // ---- Clicking a highlighted passage jumps to its comment
  document.querySelectorAll("#essay-text mark[data-comments]").forEach(function (mark) {
    mark.addEventListener("click", function () {
      var target = document.getElementById(mark.dataset.comments.split(" ")[0]);
      if (!target) return;
      target.scrollIntoView({ behavior: "smooth", block: "center" });
      target.classList.add("flash");
      setTimeout(function () { target.classList.remove("flash"); }, 1600);
    });
  });
})();
