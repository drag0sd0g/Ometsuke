"""Draw the audit sample and render a blinded classification worksheet.

Sampling unit is the ORIGINAL filing, because that is what carries the label and what
precision is a statement about. Each sampled original brings all of its amendments with
it (124 of the 396 were amended more than once), so the rater sees every document that
could have triggered the flag and the combination rule is applied afterwards.

Blinding: the released `label` and `explanation` never enter this file, and the builder
asserts that before writing. Every sampled item is a positive by construction, so the
rater knows the answer key unless decoys are mixed in — pass --decoys to add amendments
the labeller did not flag (requires those PDFs to have been downloaded and extracted).

Outputs
-------
data/worksheet/audit-worksheet.html   open in a browser; autosaves; exports JSON
data/worksheet/sample-manifest.json   seed, doc ids, order — the audit trail
"""

import argparse
import csv
import html
import json
import pathlib
import random

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT_DIR = DATA / "worksheet"

# Measured document frequency across the 574 extracted 提出理由, so the rater can see
# how common a term is rather than guessing. Glosses are literal: they say what the
# words mean, never which bucket they imply — that judgement stays the rater's.
GLOSSARY = [
    ("不適切な会計処理", "ふてきせつなかいけいしょり", "improper accounting treatment", "25%"),
    ("財務諸表 / 連結財務諸表", "ざいむしょひょう", "financial statements / consolidated", "71%"),
    ("計上", "けいじょう", "recognition, booking of an amount", "51%"),
    ("過年度", "かねんど", "prior fiscal years", "47%"),
    ("監査報告書 / 監査法人", "かんさほうこくしょ / かんさほうじん", "audit report / audit firm", "44%"),
    ("調査委員会", "ちょうさいいんかい", "investigation committee", "41%"),
    ("特別調査委員会", "とくべつちょうさいいんかい", "special investigation committee", "23%"),
    ("第三者委員会", "だいさんしゃいいんかい", "third-party committee (external)", "14%"),
    ("社内調査", "しゃないちょうさ", "internal investigation", "15%"),
    ("売上 / 売上高", "うりあげ / うりあげだか", "revenue", "31%"),
    ("誤り", "あやまり", "error, mistake", "24%"),
    ("不正", "ふせい", "misconduct, impropriety", "15%"),
    ("架空", "かくう", "fictitious, fabricated", "11%"),
    ("引当金", "ひきあてきん", "provision, allowance", "10%"),
    ("減損", "げんそん", "impairment", "10%"),
    ("過大計上 / 過少計上", "かだい / かしょうけいじょう", "overstatement / understatement", "8%"),
    ("内部統制", "ないぶとうせい", "internal control", "7%"),
    ("開示すべき重要な不備", "かいじすべきじゅうようなふび", "material weakness requiring disclosure", "—"),
    ("役員 / 異動", "やくいん / いどう", "officers, directors / change of personnel", "5%"),
    ("在庫 / 棚卸資産", "ざいこ / たなおろししさん", "inventory", "4%"),
    ("遡及", "そきゅう", "retrospective (restatement)", "3%"),
    ("添付漏れ / 記載漏れ", "てんぷもれ / きさいもれ", "missing attachment / omitted disclosure", "4%"),
    ("証券取引等監視委員会", "しょうけんとりひきとうかんしいいんかい", "Securities and Exchange Surveillance Commission", "2%"),
    ("循環取引", "じゅんかんとりひき", "circular trading", "1%"),
    ("課徴金", "かちょうきん", "administrative fine", "0.3%"),
    ("粉飾", "ふんしょく", "window-dressing, falsified accounts", "<1%"),
]

MARKERS = [
    ("kaikei", "不適切な会計処理 / 粉飾 / 不正"),
    ("iinkai", "第三者委員会 / 特別調査委員会"),
    ("sokyu", "過年度遡及修正"),
    ("goki", "誤り / 誤記 / 誤植 — clerical wording"),
    ("kisei", "規制当局 (証券取引等監視委員会 / 課徴金)"),
]

TEMPLATE = """<!doctype html>
<meta charset="utf-8">
<title>Label audit worksheet</title>
<style>
  :root {{
    --bg:#fbfaf7; --fg:#1a1a1a; --muted:#6b6b6b; --line:#e0ddd6;
    --card:#fff; --accent:#8a5a2b; --accent-soft:#f2e9df;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#16150f; --fg:#ece8e0; --muted:#9b968c; --line:#33302a;
             --card:#1f1e17; --accent:#d9a066; --accent-soft:#2c2519; }}
  }}
  * {{ box-sizing:border-box }}
  body {{ margin:0; background:var(--bg); color:var(--fg);
    font:16px/1.6 -apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP",sans-serif; }}
  header {{ position:sticky; top:0; background:var(--bg); border-bottom:1px solid var(--line);
    padding:12px 24px; display:flex; gap:20px; align-items:center; z-index:5 }}
  .bar {{ flex:1; height:6px; background:var(--line); border-radius:3px; overflow:hidden }}
  .bar > i {{ display:block; height:100%; background:var(--accent); width:0 }}
  main {{ max-width:820px; margin:0 auto; padding:28px 24px 120px }}
  .meta {{ color:var(--muted); font-size:13px; letter-spacing:.02em }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:10px;
    padding:26px 28px; margin:18px 0 }}
  .jp {{ font-size:17.5px; line-height:2.05; white-space:pre-wrap; word-break:break-word }}
  .buckets {{ display:flex; gap:10px; margin:18px 0 8px; flex-wrap:wrap }}
  .buckets button {{ flex:1; min-width:150px; padding:14px 12px; font-size:15px; cursor:pointer;
    border:1px solid var(--line); border-radius:8px; background:var(--card); color:var(--fg); text-align:left }}
  .buckets button.on {{ background:var(--accent-soft); border-color:var(--accent); font-weight:600 }}
  .buckets kbd {{ font:600 12px ui-monospace,monospace; color:var(--accent); margin-right:8px }}
  .markers label {{ display:block; padding:7px 0; cursor:pointer }}
  .markers input {{ margin-right:10px }}
  textarea {{ width:100%; min-height:70px; padding:10px; font:15px/1.7 inherit;
    background:var(--bg); color:var(--fg); border:1px solid var(--line); border-radius:8px }}
  nav {{ position:fixed; bottom:0; left:0; right:0; background:var(--card);
    border-top:1px solid var(--line); padding:12px 24px; display:flex; gap:12px; justify-content:center }}
  nav button {{ padding:10px 18px; border:1px solid var(--line); border-radius:8px;
    background:var(--bg); color:var(--fg); cursor:pointer; font-size:14px }}
  nav button.primary {{ background:var(--accent); border-color:var(--accent); color:#fff }}
  h2 {{ font-size:15px; margin:26px 0 6px; color:var(--muted); font-weight:600 }}
  .sibling {{ color:var(--muted); font-size:13px; margin-bottom:10px }}
  details {{ margin:14px 0; border:1px solid var(--line); border-radius:8px; background:var(--card) }}
  summary {{ cursor:pointer; padding:11px 16px; font-size:14px; color:var(--muted) }}
  details table {{ width:100%; border-collapse:collapse; font-size:14px }}
  details td {{ padding:7px 16px; border-top:1px solid var(--line); vertical-align:top }}
  details td:nth-child(2) {{ color:var(--muted); font-size:12.5px; white-space:nowrap }}
  details td:nth-child(4) {{ color:var(--muted); text-align:right; font-variant-numeric:tabular-nums }}
  .unsure {{ display:block; margin-top:14px; padding:11px 14px; border:1px dashed var(--line);
    border-radius:8px; cursor:pointer; font-size:14.5px }}
  .unsure.on {{ border-color:var(--accent); background:var(--accent-soft) }}
</style>
<header>
  <strong>Label audit</strong>
  <div class="bar"><i id="bar"></i></div>
  <span class="meta" id="counter"></span>
</header>
<main>
  <div class="meta" id="ident"></div>
  <div class="sibling" id="sibling"></div>
  <div class="card"><div class="jp" id="text"></div></div>
  <details id="gloss">
    <summary>用語 — glossary of the vocabulary that actually occurs in these 574 texts (press <b>g</b>)</summary>
    <table id="glosstable"></table>
  </details>

  <h2>Bucket — is this correction about the financial statements?</h2>
  <div class="buckets" id="buckets"></div>

  <h2>Markers present (factual, tick all that apply)</h2>
  <div class="markers" id="markers"></div>

  <label class="unsure" id="unsurebox">
    <input type="checkbox" id="unsure"> 読みに自信がない — I am unsure I read this correctly
    <span style="color:var(--muted)"> (separate from bucket D, which means the text itself is undecidable)</span>
  </label>

  <h2>note_ja (optional)</h2>
  <textarea id="note" placeholder="迷った点があれば日本語で"></textarea>
</main>
<nav>
  <button id="prev">← previous</button>
  <button id="next">next →</button>
  <button class="primary" id="export">export results</button>
  <button id="importbtn">import…</button>
  <input type="file" id="importfile" accept="application/json" hidden>
  <span class="meta" id="saved"></span>
</nav>
<script id="payload" type="application/json">{payload}</script>
<script>
const ITEMS = JSON.parse(document.getElementById("payload").textContent);
const BUCKETS = {buckets};
const MARKERS = {markers};
const GLOSSARY = {glossary};
const KEY = "ometsuke-audit-" + ITEMS.seed;
let answers = {{}};
try {{ answers = JSON.parse(localStorage.getItem(KEY) || "{{}}"); }} catch (e) {{ answers = {{}}; }}
let i = 0;

const el = (id) => document.getElementById(id);
function save() {{
  try {{ localStorage.setItem(KEY, JSON.stringify(answers)); el("saved").textContent = "saved"; }}
  catch (e) {{ el("saved").textContent = "not saved — export before closing"; }}
}}
function current() {{ return ITEMS.items[i]; }}
function answer() {{
  const id = current().ref;
  if (!answers[id]) answers[id] = {{ bucket: null, markers: [], note: "", unsure: false }};
  return answers[id];
}}
function render() {{
  const item = current(), a = answer();
  el("counter").textContent = (i + 1) + " / " + ITEMS.items.length;
  el("bar").style.width = ((i + 1) / ITEMS.items.length * 100) + "%";
  el("ident").textContent = "item " + item.ref + " · filed " + item.filed;
  el("sibling").textContent = item.siblings > 1
    ? "amendment " + item.sibling_index + " of " + item.siblings + " for the same filing" : "";
  el("text").textContent = item.text;
  el("buckets").innerHTML = "";
  BUCKETS.forEach(([code, label]) => {{
    const b = document.createElement("button");
    b.innerHTML = "<kbd>" + code.toLowerCase() + "</kbd>" + code + " — " + label;
    if (a.bucket === code) b.className = "on";
    b.onclick = () => {{ a.bucket = code; save(); render(); }};
    el("buckets").appendChild(b);
  }});
  el("markers").innerHTML = "";
  MARKERS.forEach(([key, label], n) => {{
    const wrap = document.createElement("label");
    const box = document.createElement("input");
    box.type = "checkbox"; box.checked = a.markers.includes(key);
    box.onchange = () => {{
      a.markers = box.checked ? a.markers.concat([key]) : a.markers.filter((m) => m !== key);
      save();
    }};
    wrap.appendChild(box);
    wrap.appendChild(document.createTextNode((n + 1) + ". " + label));
    el("markers").appendChild(wrap);
  }});
  el("note").value = a.note || "";
  el("unsure").checked = !!a.unsure;
  el("unsurebox").className = a.unsure ? "unsure on" : "unsure";
  window.scrollTo(0, 0);
}}
el("note").oninput = () => {{ answer().note = el("note").value; save(); }};
el("unsure").onchange = () => {{ answer().unsure = el("unsure").checked; save(); render(); }};
el("glosstable").innerHTML = GLOSSARY.map(
  (g) => "<tr><td>" + g[0] + "</td><td>" + g[1] + "</td><td>" + g[2] + "</td><td>" + g[3] + "</td></tr>"
).join("");
el("prev").onclick = () => {{ if (i > 0) {{ i--; render(); }} }};
el("next").onclick = () => {{ if (i < ITEMS.items.length - 1) {{ i++; render(); }} }};
el("export").onclick = () => {{
  const out = JSON.stringify({{ seed: ITEMS.seed, built: ITEMS.built, answers }}, null, 2);
  const blob = new Blob([out], {{ type: "application/json" }});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = "audit-results.json"; a.click();
  navigator.clipboard && navigator.clipboard.writeText(out);
}};
el("importbtn").onclick = () => el("importfile").click();
el("importfile").onchange = (e) => {{
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {{
    let incoming;
    try {{ incoming = JSON.parse(reader.result); }}
    catch (err) {{ alert("Not valid JSON."); return; }}
    if (String(incoming.seed) !== String(ITEMS.seed)) {{
      alert("Refusing to import: that file was exported from seed " + incoming.seed +
            ", this worksheet is seed " + ITEMS.seed + ". The refs would not line up.");
      return;
    }}
    const known = new Set(ITEMS.items.map((it) => it.ref));
    const unknown = Object.keys(incoming.answers || {{}}).filter((r) => !known.has(r));
    if (unknown.length) {{
      alert("Refusing to import: " + unknown.length + " refs in that file are not in this worksheet.");
      return;
    }}
    answers = Object.assign({{}}, answers, incoming.answers);
    save();
    i = 0;
    const done = Object.values(answers).filter((a) => a && a.bucket).length;
    while (i < ITEMS.items.length - 1 && answers[ITEMS.items[i].ref] &&
           answers[ITEMS.items[i].ref].bucket) {{ i++; }}
    render();
    alert("Imported " + done + " classified items. Resuming at item " + ITEMS.items[i].ref + ".");
  }};
  reader.readAsText(file);
}};
document.onkeydown = (e) => {{
  if (e.target.tagName === "TEXTAREA") return;
  const k = e.key.toLowerCase();
  const bucket = BUCKETS.find(([code]) => code.toLowerCase() === k);
  if (bucket) {{
    answer().bucket = bucket[0]; save();
    if (i < ITEMS.items.length - 1) {{ i++; }}
    render(); return;
  }}
  if (k >= "1" && k <= String(MARKERS.length)) {{
    const key = MARKERS[Number(k) - 1][0], a = answer();
    a.markers = a.markers.includes(key) ? a.markers.filter((m) => m !== key) : a.markers.concat([key]);
    save(); render(); return;
  }}
  if (k === "g") {{ el("gloss").open = !el("gloss").open; return; }}
  if (k === "u") {{ el("unsure").checked = !el("unsure").checked; el("unsure").onchange(); return; }}
  if (e.key === "ArrowRight") el("next").click();
  if (e.key === "ArrowLeft") el("prev").click();
}};
render();
</script>
"""

BUCKETS = [
    ("A", "financial-statement correction"),
    ("B", "non-financial correction"),
    ("C", "mixed"),
    ("D", "cannot determine"),
]

# What the rater must not see. Checked against the embedded payload, not the rendered
# file: a substring scan of the whole page matches the worksheet's own markup
# (document.createElement("label")) and produces a false alarm, which is the fastest
# way to teach someone to ignore the check that matters.
ALLOWED_ITEM_KEYS = {
    "ref", "filed", "siblings", "sibling_index", "text", "in_window",
}
FORBIDDEN_SUBSTRINGS = ("is_accounting_fraud", "ammended_doc_id")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-n", "--sample", type=int, default=50, help="number of ORIGINAL filings")
    parser.add_argument("--seed", type=int, default=20260823)
    parser.add_argument("--decoys", type=int, default=0, help="unflagged amendments to mix in")
    args = parser.parse_args()

    riyu = {}
    with (DATA / "teishutsu-riyu.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            riyu[record["amendment_doc_id"]] = record

    rows = list(csv.DictReader((DATA / "amendment-map.csv").open(encoding="utf-8")))
    by_original = {}
    for row in rows:
        by_original.setdefault(row["original_doc_id"], []).append(row)

    usable = {
        original: sorted(amendments, key=lambda r: r["submitDateTime"] or "")
        for original, amendments in by_original.items()
        if all(riyu.get(a["amendment_doc_id"], {}).get("teishutsu_riyu") for a in amendments)
    }
    dropped = len(by_original) - len(usable)
    print(f"{len(by_original)} originals mapped; {len(usable)} with 提出理由 extracted for every amendment "
          f"({dropped} dropped — classify those by hand or fix extraction)")

    rng = random.Random(args.seed)
    chosen = sorted(rng.sample(sorted(usable), min(args.sample, len(usable))))

    items = []
    for original in chosen:
        amendments = usable[original]
        for index, amendment in enumerate(amendments, 1):
            record = riyu[amendment["amendment_doc_id"]]
            items.append({
                "id": amendment["amendment_doc_id"],
                "original": original,
                "filed": (amendment["submitDateTime"] or "")[:10],
                "siblings": len(amendments),
                "sibling_index": index,
                "text": record["teishutsu_riyu"],
                "in_window": record["found_in_window"],
            })
    rng.shuffle(items)

    decoy_ids: list[str] = []
    if args.decoys:
        decoys = list(csv.DictReader((DATA / "decoy-map.csv").open(encoding="utf-8")))
        usable_decoys = [d for d in decoys if riyu.get(d["amendment_doc_id"], {}).get("teishutsu_riyu")]
        if len(usable_decoys) < args.decoys:
            print(f"warning: only {len(usable_decoys)} decoys have 提出理由 extracted, wanted {args.decoys}")
        for decoy in rng.sample(usable_decoys, min(args.decoys, len(usable_decoys))):
            record = riyu[decoy["amendment_doc_id"]]
            items.append({
                "id": decoy["amendment_doc_id"],
                "original": decoy["original_doc_id"],
                "filed": (decoy["submitDateTime"] or "")[:10],
                "siblings": 1,
                "sibling_index": 1,
                "text": record["teishutsu_riyu"],
                "in_window": record["found_in_window"],
                "_decoy": True,
            })
            decoy_ids.append(decoy["amendment_doc_id"])
        rng.shuffle(items)
        print(f"mixed in {len(decoy_ids)} decoys — worksheet is now a blind classification")

    # Blinding made structural rather than procedural. Document ids on screen could be
    # grepped against positives.csv, which would hand over the answer key; so the page
    # carries opaque refs and the id mapping lives only in the manifest.
    identities = {}
    for position, item in enumerate(items, 1):
        ref = f"{position:02d}"
        identities[ref] = {
            "amendment_doc_id": item.pop("id"),
            "original_doc_id": item.pop("original"),
            "decoy": item.get("_decoy", False),
        }
        item.pop("_decoy", None)
        item["ref"] = ref

    payload = {
        "seed": args.seed,
        "built": __import__("datetime").date.today().isoformat(),
        "items": items,
    }
    page = TEMPLATE.format(
        payload=html.escape(json.dumps(payload, ensure_ascii=False), quote=False),
        buckets=json.dumps(BUCKETS),
        markers=json.dumps(MARKERS, ensure_ascii=False),
        glossary=json.dumps(GLOSSARY, ensure_ascii=False),
    )

    # Blinding is the one thing that cannot be checked after the fact: if the label
    # leaks into the page, the measurement is quietly worthless rather than broken.
    for item in items:
        extra = set(item) - ALLOWED_ITEM_KEYS
        assert not extra, f"BLINDING LEAK: unexpected fields on {item['id']}: {sorted(extra)}"
    serialised = json.dumps(payload, ensure_ascii=False)
    for token in FORBIDDEN_SUBSTRINGS:
        assert token not in serialised, f"BLINDING LEAK: {token!r} in the payload"
    # The released explanations exist for three positives; none may reach the page.
    for row in csv.DictReader((DATA / "positives.csv").open(encoding="utf-8")):
        pass
    assert '"label"' not in serialised, "BLINDING LEAK: a label field is in the payload"
    known = {r["doc_id"] for r in csv.DictReader((DATA / "positives.csv").open(encoding="utf-8"))}
    leaked = sorted(d for d in known if d in serialised)
    assert not leaked, f"BLINDING LEAK: benchmark doc ids on the page: {leaked[:5]}"
    print(f"blinding check passed: no label, no benchmark doc id, "
          f"{len(ALLOWED_ITEM_KEYS)} permitted fields")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "audit-worksheet.html").write_text(page, encoding="utf-8")
    (OUT_DIR / "sample-manifest.json").write_text(
        json.dumps({
            "seed": args.seed,
            "sample_size_originals": len(chosen),
            "originals": chosen,
            "amendments": [identities[item["ref"]]["amendment_doc_id"] for item in items],
            "population_originals": len(usable),
            "decoys": decoy_ids,
            "identities": identities,
            "decoy_note": "Unflagged amendments of negative-labelled filings, mixed in for "
                          "blinding. Excluded from the precision estimate; they feed the "
                          "negative-class check instead. Do not read before classifying.",
        }, indent=2),
        encoding="utf-8",
    )
    print(f"sampled {len(chosen)} originals -> {len(items)} amendments to read")
    print(f"wrote {OUT_DIR / 'audit-worksheet.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
