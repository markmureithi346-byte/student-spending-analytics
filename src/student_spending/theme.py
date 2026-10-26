"""Shared visual language for the report and the interactive dashboard."""

from __future__ import annotations

BASE_CSS = """
:root {
  color-scheme: dark;
  --ink: #f8f4ff;
  --muted: #c3b1e0;
  --line: rgba(196, 181, 253, .16);
  --accent: #c4b5fd;
  --accent-2: #e879f9;
  --danger: #fda4af;
  --danger-soft: rgba(190, 24, 93, .2);
  --success: #6ee7b7;
  --success-soft: rgba(5, 150, 105, .18);
  --panel: rgba(38, 16, 68, .92);
  --surface: #241041;
  --surface-2: #1b0933;
  --panel-line: rgba(196, 181, 253, .18);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0; min-height: 100vh; padding: 30px 20px 72px;
  background: #0a0414; color: #f7f3ff;
  font-family: "Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, sans-serif;
  line-height: 1.55; -webkit-font-smoothing: antialiased;
}
.scene { position: fixed; inset: 0; z-index: -1; overflow: hidden;
         background: linear-gradient(150deg, #09020f 0%, #1d0739 38%,
                     #2b0c52 64%, #0d031c 100%);
         background-size: 180% 180%;
         animation: scene-breathe 34s ease-in-out infinite alternate; }
.scene::before { content: ""; position: absolute; inset: -20%; z-index: 0;
  background-image: radial-gradient(rgba(255,255,255,.55) 1px, transparent 1.4px);
  background-size: 46px 46px; opacity: .12;
  -webkit-mask-image: radial-gradient(ellipse at 50% 22%, #000 8%, transparent 70%);
  mask-image: radial-gradient(ellipse at 50% 22%, #000 8%, transparent 70%);
  animation: scene-stars 70s linear infinite; }
.scene::after { content: ""; position: absolute; inset: -35%; z-index: 0;
  background: conic-gradient(from 0deg at 50% 50%, transparent 0deg,
    rgba(168,85,247,.16) 65deg, transparent 145deg, rgba(217,70,239,.12) 235deg,
    transparent 320deg);
  opacity: .7; animation: scene-turn 90s linear infinite; }
.orb { position: absolute; z-index: 1; border-radius: 50%; filter: blur(85px);
       opacity: .55; animation: drift 26s ease-in-out infinite alternate; }
.orb-a { width: 46vw; height: 46vw; top: -14vh; left: -10vw; background: #7c3aed; }
.orb-b { width: 38vw; height: 38vw; top: 6vh; right: -10vw; background: #d946ef;
         opacity: .38; animation-duration: 31s; animation-delay: -8s; }
.orb-c { width: 44vw; height: 44vw; bottom: -20vh; left: 26vw; background: #4f46e5;
         opacity: .45; animation-duration: 36s; animation-delay: -16s; }
.orb-d { width: 30vw; height: 30vw; top: 46vh; right: 16vw; background: #a855f7;
         opacity: .3; animation-duration: 42s; animation-delay: -22s; }
@keyframes scene-breathe {
  0% { background-position: 0% 18%; }
  50% { background-position: 100% 55%; }
  100% { background-position: 28% 100%; }
}
@keyframes scene-stars { to { transform: translate3d(-46px, 46px, 0); } }
@keyframes scene-turn { to { transform: rotate(360deg); } }
@keyframes drift {
  0% { transform: translate3d(0, 0, 0) scale(1); }
  50% { transform: translate3d(3vw, 4vh, 0) scale(1.07); }
  100% { transform: translate3d(-4vw, -3vh, 0) scale(.95); }
}
.skip { position: absolute; left: -999px; top: 8px; background: #f3e8ff; color: #4c1d95;
        padding: 8px 14px; border-radius: 8px; z-index: 100; }
.skip:focus { left: 16px; }
.shell { width: 100%; max-width: 1060px; margin: 0 auto; }
.hero { padding: 10px 6px 4px; }
.eyebrow { display: flex; align-items: center; gap: 8px; margin: 0 0 10px;
           font-size: 12px; letter-spacing: .14em; text-transform: uppercase;
           color: #d8c4f7; font-weight: 600; }
.hero h1 { margin: 0 0 12px; font-size: clamp(34px, 5vw, 54px); line-height: 1.05;
           letter-spacing: -.035em; font-weight: 700; color: #fff; }
.hero h1 span { background: linear-gradient(100deg, #e9d5ff, #f0abfc 48%, #c4b5fd);
                -webkit-background-clip: text; background-clip: text; color: transparent; }
.lede { max-width: 720px; margin: 0 0 20px; font-size: 17px; color: #ded1f5; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 18px; padding: 0; list-style: none; }
.chips li { display: inline-flex; align-items: center; gap: 8px; padding: 6px 12px;
            border: 1px solid rgba(255,255,255,.18); border-radius: 999px;
            background: rgba(255,255,255,.08); color: #f3e8ff; font-size: 12.5px;
            backdrop-filter: blur(8px); }
.chip-key { color: #c4b0e6; text-transform: uppercase; letter-spacing: .08em;
            font-size: 10.5px; font-weight: 700; }
.chips code { background: rgba(255,255,255,.14); color: #fff;
              padding: 1px 6px; border-radius: 5px; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: #34d399;
              display: inline-block; box-shadow: 0 0 0 3px rgba(52,211,153,.2); }
.status-dot.bad { background: #fb7185; box-shadow: 0 0 0 3px rgba(251,113,133,.2); }
.disclaimer { max-width: 820px; margin: 0 0 26px; padding: 12px 16px; border-radius: 12px;
              background: rgba(76, 45, 6, .45);
              border: 1px solid rgba(251, 191, 36, .35);
              color: #fde68a; font-size: 13px; }
.disclaimer strong { color: #fcd34d; }
.toc { position: sticky; top: 12px; z-index: 30; display: flex; flex-wrap: wrap; gap: 4px;
       margin: 0 0 20px; padding: 7px; border-radius: 22px;
       background: rgba(19, 7, 36, .78); border: 1px solid rgba(196,181,253,.2);
       backdrop-filter: blur(18px); box-shadow: 0 18px 40px -22px rgba(0,0,0,.9); }
.toc a { flex: 0 0 auto; padding: 7px 13px; border-radius: 999px; color: #e7daf9;
         text-decoration: none; font-size: 13px; font-weight: 600;
         transition: background-color .15s ease, color .15s ease; }
.toc a:hover, .toc a:focus-visible { background: rgba(168, 85, 247, .3); color: #fff; outline: none; }
.panel { background:
           radial-gradient(120% 80% at 0% 0%, rgba(168,85,247,.13), transparent 55%),
           linear-gradient(160deg, rgba(46, 20, 82, .96), rgba(25, 9, 48, .97));
         color: var(--ink); border-radius: 22px;
         padding: 26px 28px 28px; margin: 0 0 22px;
         border: 1px solid var(--panel-line);
         box-shadow: 0 34px 70px -34px rgba(4, 0, 12, .95),
                     inset 0 1px 0 rgba(255,255,255,.05);
         backdrop-filter: blur(10px); scroll-margin-top: 86px; }
.panel .eyebrow { color: #d8b4fe; }
.panel .section-no { color: var(--accent-2); font-variant-numeric: tabular-nums; }
.panel h2 { margin: 0 0 6px; font-size: 24px; letter-spacing: -.02em; color: #fff; }
.panel h3 { margin: 26px 0 4px; font-size: 16px; letter-spacing: -.01em; color: #f1e7ff; }
.lead { margin: 0 0 18px; color: var(--muted); font-size: 14.5px; max-width: 78ch; }
.section-note { margin: 4px 0 12px; color: var(--muted); font-size: 13px; }
.cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
         gap: 12px; margin: 18px 0 6px; }
.card { position: relative; padding: 15px 17px 16px; border-radius: 16px; overflow: hidden;
        background: linear-gradient(155deg, rgba(69, 31, 114, .92),
                    rgba(39, 17, 70, .96) 70%, rgba(30, 12, 55, .98));
        border: 1px solid rgba(192, 132, 252, .26);
        box-shadow: inset 0 1px 0 rgba(255,255,255,.06);
        transition: transform .18s ease, box-shadow .18s ease; }
.card::before { content: ""; position: absolute; inset: 0 0 auto; height: 3px;
                background: linear-gradient(90deg, #a855f7, #f0abfc); opacity: .9; }
.card:hover { transform: translateY(-2px);
              box-shadow: 0 16px 30px -18px rgba(217, 70, 239, .7); }
.card .label { font-size: 11px; font-weight: 700; text-transform: uppercase;
               letter-spacing: .07em; color: #d8b4fe; }
.card .value { margin-top: 5px; font-size: clamp(19px, 2vw, 23px); font-weight: 700;
               color: #fff; white-space: nowrap; font-variant-numeric: tabular-nums;
               letter-spacing: -.02em; }
.card .hint { margin-top: 2px; font-size: 12px; color: #bda9dd; }
.headline { margin: 16px 0 4px; font-size: 15px; color: #e9ddfa; }
.headline strong { color: #d8b4fe; }
.banner { display: flex; flex-wrap: wrap; gap: 6px; align-items: baseline;
          margin: 6px 0 16px; padding: 12px 15px; border-radius: 12px; font-size: 13.5px; }
.banner strong { font-weight: 700; }
.banner.good { background: var(--success-soft); border: 1px solid rgba(110,231,183,.32);
               color: #a7f3d0; }
.banner.bad { background: var(--danger-soft); border: 1px solid rgba(253,164,175,.32);
              color: #fecdd3; }
.table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 14px;
              background: rgba(11, 4, 24, .45); -webkit-overflow-scrolling: touch; }
table { width: 100%; border-collapse: collapse; font-size: 14px; min-width: 520px; }
th, td { padding: 10px 13px; text-align: left; border-bottom: 1px solid var(--line);
         vertical-align: top; }
thead th { background: rgba(124, 58, 237, .18); color: #ddc9f8; font-size: 11.5px;
           text-transform: uppercase; letter-spacing: .06em; font-weight: 700;
           white-space: nowrap; }
tbody tr:nth-child(even) { background: rgba(255, 255, 255, .025); }
tbody tr:hover { background: rgba(168, 85, 247, .13); }
tbody tr:last-child td { border-bottom: none; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
tr.alert td { background: rgba(190, 24, 93, .2); color: #fecdd3; }
tr.alert:hover td { background: rgba(190, 24, 93, .28); }
tr.over td { background: rgba(154, 52, 18, .16); color: #fde4d9; }
tr.over:hover td { background: rgba(154, 52, 18, .24); }
tr.over td:last-child { color: var(--danger); font-weight: 700; }
tr.total td { background: rgba(124, 58, 237, .16); color: #fff; font-weight: 700;
              border-top: 1px solid rgba(196, 181, 253, .36); }
tr.total:hover td { background: rgba(124, 58, 237, .22); }
.pill { display: inline-block; padding: 2px 9px; border-radius: 999px;
        font-size: 11.5px; font-weight: 700; letter-spacing: .03em; }
.pass { background: rgba(5, 150, 105, .2); color: var(--success); }
.fail { background: rgba(190, 24, 93, .24); color: var(--danger); }
.panel code { background: rgba(124, 58, 237, .24); color: #e9d5ff; padding: 2px 7px;
              border-radius: 5px; font-size: 12.5px; }
.panel table code { white-space: nowrap; }
.share { display: inline-flex; align-items: center; gap: 8px; justify-content: flex-end; }
.share-track { width: 64px; height: 6px; border-radius: 999px;
               background: rgba(196, 181, 253, .18); overflow: hidden; }
.share-fill { display: block; height: 100%; border-radius: inherit;
              background: linear-gradient(90deg, #a855f7, #e879f9); }
.share-value { min-width: 42px; text-align: right; font-variant-numeric: tabular-nums; }
.chart-wrap { overflow-x: auto; margin-bottom: 14px; border-radius: 14px; }
.chart-hint { display: none; }
.chart { display: block; width: 100%; height: auto; background: #180829;
         border: 1px solid var(--line); border-radius: 14px; padding: 12px 14px; }
.chart text { font-family: inherit; font-size: 12px; fill: #e7dcf8; }
.chart .bar-label { fill: #e7dcf8; }
.chart .bar-value { fill: #c4b5fd; font-variant-numeric: tabular-nums; }
.chart .bar-value.small { font-size: 10.5px; }
.chart .guide { stroke: rgba(196, 181, 253, .18); stroke-width: 1; }
.chart-legend { display: flex; flex-wrap: wrap; gap: 6px 16px; margin: 0 0 10px;
                font-size: 12.5px; color: var(--muted); }
.chart-legend span { display: inline-flex; align-items: center; gap: 6px; }
.chart-legend i { display: inline-block; width: 20px; height: 8px; border-radius: 999px; }
footer.footer { margin: 4px 0 0; }
.footer p { margin: 0 0 8px; color: var(--muted); font-size: 13px; }
.footer strong { color: var(--ink); }
.footer .meta-line { font-size: 12px; }
.totop { display: inline-flex; margin-top: 6px; color: var(--accent);
         font-weight: 600; font-size: 13px; text-decoration: none; }
.totop:hover { text-decoration: underline; }
.panel:target { outline: 3px solid rgba(168, 85, 247, .45); outline-offset: 3px; }
@media (max-width: 900px) {
  .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 640px) {
  body { padding: 18px 12px 48px; }
  .hero { padding: 6px 4px 0; }
  .lede { font-size: 15.5px; }
  .panel { padding: 20px 16px 22px; border-radius: 18px; scroll-margin-top: 118px; }
  .panel h2 { font-size: 21px; }
  .card .value { font-size: 19px; }
  .chart { min-width: 540px; }
  .chart-hint { display: block; margin: -4px 0 8px; color: var(--muted); font-size: 11.5px; }
  .toc { top: 8px; border-radius: 18px; gap: 2px; padding: 6px; }
  .toc a { padding: 6px 9px; font-size: 12px; }
  .table-wrap { border: 0; background: transparent; overflow: visible; }
  table { display: block; min-width: 0; font-size: 13.5px; }
  thead { display: none; }
  tbody { display: block; }
  tbody tr { display: block; margin: 0 0 10px; overflow: hidden;
             border: 1px solid var(--line); border-radius: 12px; background: #241041; }
  tbody tr:nth-child(even) { background: #2a1249; }
  tbody tr:hover { background: inherit; }
  td { display: flex; align-items: baseline; justify-content: space-between; gap: 12px;
       padding: 7px 12px; border-bottom: 1px solid rgba(196, 181, 253, .12);
       text-align: right; white-space: normal; }
  td:last-child { border-bottom: 0; }
  td::before { content: attr(data-label); flex: 0 0 40%; text-align: left;
               font-size: 10.5px; font-weight: 700; text-transform: uppercase;
               letter-spacing: .06em; color: var(--muted); }
  td.num { white-space: normal; }
  td:has(code) { display: block; text-align: left; }
  td:has(code)::before { display: block; margin-bottom: 3px; }
  .panel table code { white-space: nowrap; font-size: 11px; }
  tr.alert td, tr.over td, tr.total td { background: transparent; }
  tr.alert { background: rgba(190, 24, 93, .22); }
  tr.over { background: rgba(154, 52, 18, .2); }
  tr.over td:last-child { font-weight: 700; }
  tr.alert:hover td, tr.over:hover td { background: transparent; }
  .share { justify-content: flex-end; }
}
@media (max-width: 380px) {
  .cards { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  .scene, .scene::before, .scene::after, .orb, .receipt::before { animation: none; }
  .card { transition: none; }
}
@media print {
  :root { color-scheme: light; }
  body { background: #fff; color: #000; padding: 0; }
  .scene, .toc, .skip, .totop { display: none !important; }
  .hero h1, .hero h1 span { color: #2e1065; -webkit-text-fill-color: #2e1065;
                            background: none; }
  .lede, .eyebrow, .chips li { color: #333; }
  .chips li { background: #f5f5f5; border-color: #ddd; }
  .chips code { color: #000; }
  .disclaimer { background: #fff; border-color: #ccc; color: #000; }
  .panel { background: #fff !important; color: #111; box-shadow: none;
           border: 1px solid #ddd; break-inside: avoid; }
  .panel h2, .panel h3, .panel p, .panel li, .panel td, .panel th, .panel strong,
  .panel dd, .panel dt, .panel .lead, .panel .section-note,
  .panel .plan-section-note, .card .value, .card .label, .card .hint,
  .headline, .headline strong, .footer p, .footer strong { color: #111 !important; }
  .card, .table-wrap, .chart { background: #fff !important; border-color: #ddd; }
  .card { box-shadow: none; }
  .card::before { display: none; }
  thead th { background: #eee !important; color: #111 !important; }
  tbody tr:nth-child(even), tbody tr:hover, tr.total td,
  tr.alert td, tr.over td { background: #fff !important; color: #111 !important; }
  th, td { border-color: #ddd; }
  .banner.good, .banner.bad, .banner.note { background: #fff; color: #000;
                                           border-color: #ccc; }
  .pill, .plan-tag { background: #fff !important; color: #000 !important;
                     border: 1px solid #bbb; }
  .share-track { background: #eee; }
  .share-fill { background: #555 !important; }
  .chart text, .chart .bar-label, .chart .bar-value { fill: #111 !important; }
  .chart .guide { stroke: #ccc !important; }
  a { color: #000; text-decoration: none; }
}
"""
