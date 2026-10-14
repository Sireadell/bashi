(function () {
  var panel = document.getElementById('whatif-panel');
  var B = window.BASHI;
  function esc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }
  document.querySelectorAll('button[data-remove]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var id = btn.getAttribute('data-remove');
      document.querySelectorAll('button[data-remove]').forEach(function (b) { b.classList.remove('on'); });
      btn.classList.add('on');
      panel.hidden = false;
      panel.className = 'whatif';
      panel.innerHTML = '<p>Copying the graph and removing ' + esc(id) + '. The real data is not touched.</p>';
      panel.scrollIntoView({behavior: 'smooth', block: 'nearest'});
      fetch('/whatif/' + encodeURIComponent(B.decision), {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({remove: [id]})
      }).then(function (r) { return r.json(); }).then(function (res) {
        if (res.error) { panel.innerHTML = '<p class="err">' + esc(res.error) + '</p>'; return; }
        var flip = res.changed;
        var nv = res.new_verdict === 'CANNOT_TRACE';
        var nvText = nv ? 'CANNOT TRACE' : res.new_verdict;
        panel.className = 'whatif ' + (flip ? 'flipped' : 'same');
        panel.innerHTML =
          '<p class="kicker">What if ' + esc(id) + ' did not exist</p>' +
          '<div class="pair">' +
            '<div class="side"><span class="lbl">Real answer</span><span class="v ' + res.original_verdict.toLowerCase() + '">' + esc(res.original_verdict) + '</span></div>' +
            '<span class="arrow" aria-hidden="true">&rarr;</span>' +
            '<div class="side"><span class="lbl">On a copy without it</span><span class="v ' + (nv ? 'cant' : res.new_verdict.toLowerCase()) + '">' + esc(nvText) + '</span></div>' +
          '</div>' +
          (nv ? '<p><b>Cannot trace this amount</b> without that record, so no answer is given.</p>' : flip ? '<p>That one record was the reason. ' + esc(res.new_reason || '') + '.</p>'
                : '<p><b>EVIDENCE DID NOT MATTER.</b> The answer is the same without it.</p>') +
          '<p class="small">The copy was deleted straight away. The real data is unchanged.</p>';
      }).catch(function () {
        panel.innerHTML = '<p class="err">The what-if could not run. Try again.</p>';
      });
    });
  });
})();
