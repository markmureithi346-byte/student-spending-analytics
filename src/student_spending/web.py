"""Interactive, read-only spending dashboard served by the standard library.

Every figure on the page comes from a parameterised query against the same SQL
views the static report uses. The server binds to loopback by default, opens
the warehouse in read-only mode and never accepts writes. Filters are ordinary
GET form fields, so the page needs no JavaScript and every view is bookmarkable.
"""

from __future__ import annotations

import contextvars
import csv
import hmac
import html
import io
import ipaddress
import json
import logging
import sqlite3
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass, replace
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__, config, legal
from .accounts import (
    MAX_DISPLAY_NAME_LENGTH,
    MAX_EMAIL_LENGTH,
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    SESSION_COOKIE,
    SESSION_SECONDS,
    Account,
    AccountError,
    AccountStore,
    validate_display_name,
    validate_email,
    validate_password,
)
from .components import (
    bar_chart,
    display_share_pcts,
    grouped_bar_chart,
    integer,
    money,
    percent,
    share_cell,
    table,
)
from .coach import (
    MAX_QUESTION_LENGTH,
    CoachReply,
    answer as coach_answer,
    suggest as coach_suggest,
)
from .personal import (
    BUDGET_METHODS,
    CATEGORY_ROWS,
    MAX_CATEGORIES,
    MAX_CATEGORY_NAME_LENGTH,
    MAX_ENTRY_NOTE_LENGTH,
    MAX_METHOD_NOTE_LENGTH,
    MAX_NAME_LENGTH,
    MAX_PLAN_REQUEST_BYTES,
    MAX_SPENDINGS,
    PERIODS,
    PERIOD_NOUNS,
    SPENDING_ROWS,
    MoneyPlan,
    PlanAnalysis,
    PlanDraft,
    PlanRequestError,
    analyse,
    parse_form,
    read_draft,
    validate_draft,
)
from .platform import (
    FILE_FIELDS,
    MAX_CSV_ROWS,
    MAX_FILE_BYTES,
    MAX_REQUEST_BYTES,
    MAX_TITLE_LENGTH,
    AnalysisWorkspace,
    PipelineFailure,
    UploadError,
    create_analysis,
    delete_analysis,
    list_analyses,
    parse_upload,
    workspace_for,
)
from .theme import BASE_CSS, scene_markup

logger = logging.getLogger(__name__)

PER_PAGE_CHOICES = (25, 50, 100)
SORT_CHOICES = {
    "newest": ("Newest first", "transaction_date DESC, transaction_id"),
    "oldest": ("Oldest first", "transaction_date, transaction_id"),
    "largest": ("Largest amount first", "amount_cents DESC, transaction_id"),
    "smallest": ("Smallest amount first", "amount_cents, transaction_id"),
}
FLAG_CHOICES = {
    "all": "All transactions",
    "anomalies": "Flagged for review only",
}
SEARCH_LIMIT = 80
MERCHANT_LIMIT = 8
SAMPLE_FILES = {
    "student_expenses.csv": config.DEFAULT_TRANSACTIONS_CSV,
}
MAX_AUTH_REQUEST_BYTES = 16 * 1024
AUTH_ATTEMPT_LIMIT = 8
AUTH_ATTEMPT_WINDOW_SECONDS = 5 * 60
LOGO_PATH = Path(__file__).resolve().parent / "assets" / "plan-it-logo.jpg"
_LOGO_CACHE: bytes | None = None


def _logo_bytes() -> bytes:
    global _LOGO_CACHE
    if _LOGO_CACHE is None:
        _LOGO_CACHE = LOGO_PATH.read_bytes()
    return _LOGO_CACHE


_DASH_CSS = """
html { scroll-behavior: auto; }
.dash-hero .hero-actions { display: flex; flex-wrap: wrap; gap: 10px; margin: 0 0 18px; }
.hero-actions .button.ghost { background: rgba(255,255,255,.1);
  border-color: rgba(255,255,255,.25); color: #f3e8ff; }
.hero-actions .button.ghost:hover { background: rgba(255,255,255,.18); }
.button { position: relative; isolation: isolate; overflow: hidden;
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  padding: 9px 16px; border-radius: 999px; border: 1px solid transparent;
  font: inherit; font-size: 13.5px; font-weight: 700; text-decoration: none;
  cursor: pointer; transition: transform .18s cubic-bezier(.2,.9,.3,1.3),
  box-shadow .18s ease, background-color .18s ease, border-color .18s ease,
  background-position .35s ease, filter .18s ease; }
.button::after, button::after { content: ""; position: absolute; inset: 0;
  background: linear-gradient(115deg, transparent 32%, rgba(255,255,255,.38) 50%,
  transparent 68%); transform: translateX(-140%) skewX(-14deg);
  transition: transform .55s ease; pointer-events: none; }
.button:hover::after, .button:focus-visible::after,
button:hover::after, button:focus-visible::after {
  transform: translateX(140%) skewX(-14deg); }
.button:hover { transform: translateY(-2px); }
.button:active { transform: translateY(0) scale(.97); }
.button:focus-visible { outline: 3px solid rgba(240,171,252,.55); outline-offset: 2px; }
.button.primary { background: linear-gradient(100deg, #7c3aed, #c026d3, #a855f7);
  background-size: 180% 100%; background-position: 0% 50%; color: #fff;
  box-shadow: 0 10px 20px -12px rgba(109, 40, 217, .8); }
.button.primary:hover { background-position: 100% 50%;
  box-shadow: 0 16px 28px -14px rgba(192,38,211,.95),
  0 0 0 1px rgba(240,171,252,.28) inset; }
.button.ghost { background: rgba(255,255,255,.06); border-color: rgba(196,181,253,.3);
  color: #e9d5ff; }
.button.ghost:hover { background: rgba(255,255,255,.13);
  border-color: rgba(240,171,252,.5);
  box-shadow: 0 10px 22px -16px rgba(240,171,252,.7); }
.button.small { padding: 6px 12px; font-size: 12.5px; }
.button.disabled { opacity: .45; cursor: not-allowed; pointer-events: none; }
.button.disabled::after { display: none; }
button { position: relative; cursor: pointer;
  transition: transform .16s ease, box-shadow .16s ease,
  background-color .16s ease, border-color .16s ease; }
button:not(.button) { isolation: isolate; overflow: hidden; }
button:not(.button):hover { transform: translateY(-1px);
  box-shadow: 0 8px 18px -12px rgba(240,171,252,.8); }
button:not(.button):active { transform: translateY(0) scale(.96); }
button:focus-visible { outline: 3px solid rgba(240,171,252,.55); outline-offset: 2px; }
.filters { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px 16px; margin-top: 14px; }
.field { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.field label { font-size: 11.5px; font-weight: 700; text-transform: uppercase;
  letter-spacing: .06em; color: #cbb6ea; }
.field input, .field select { width: 100%; padding: 9px 11px; border: 1px solid #4c2a78;
  border-radius: 10px; background: #241041; color: var(--ink); font: inherit;
  font-size: 14px; }
.field input:hover, .field select:hover { border-color: #6d3aa3; }
.field input:focus, .field select:focus { outline: 3px solid rgba(192,132,252,.25);
  border-color: var(--accent); }
.field-search { grid-column: span 2; }
.filters .actions { grid-column: span 2; display: flex; flex-wrap: wrap; gap: 10px;
  align-items: center; align-self: end; margin: 0; }
.filters .note { grid-column: 1 / -1; margin: 0; color: var(--muted); font-size: 12px; }
.dash-cards { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.resultbar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
  gap: 10px 16px; margin: 16px 0 0; padding: 12px 14px; border: 1px solid var(--line);
  border-radius: 14px; background: rgba(124,58,237,.12); }
.resultbar p { margin: 0; font-size: 13px; color: #d8c8ef; }
.resultbar .button { flex: 0 0 auto; }
.active-filters { display: flex; flex-wrap: wrap; align-items: center; gap: 6px;
  margin: 10px 0 0; padding: 0; list-style: none; }
.active-filters li { font-size: 12px; background: rgba(124,58,237,.24); color: #e9d5ff;
  padding: 3px 9px; border-radius: 999px; }
.active-filters .clear { background: transparent; color: var(--danger); font-weight: 700;
  text-decoration: none; padding: 3px 4px; }
.active-filters .clear:hover { text-decoration: underline; }
.table-meta { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px;
  margin: 0 0 10px; color: var(--muted); font-size: 12.5px; }
.cell-merchant strong { display: block; color: var(--ink); font-weight: 600; }
.cell-merchant .sub { display: block; color: var(--muted); font-size: 12px;
  max-width: 38ch; }
.pill-review { background: var(--danger-soft); color: var(--danger); }
.pager { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-top: 14px; }
.pager .page-label { font-size: 12.5px; color: var(--muted); }
.split { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.split table { min-width: 0; }
.split th, .split td { padding: 8px 10px; }
.flag-note { margin: 10px 0 0; }
.footer-links { display: flex; flex-wrap: wrap; gap: 16px; align-items: center; margin-top: 4px; }
.empty { margin: 10px 0 0; padding: 16px; border: 1px dashed rgba(196,181,253,.35);
  border-radius: 14px; background: rgba(124,58,237,.1); color: var(--muted); }
.empty strong { color: var(--ink); }
.flag-link { font-size: 12.5px; font-weight: 700; color: var(--accent); }
.error-page { margin-top: 60px; }
.error-page p { color: var(--muted); }
.upload-grid { display: grid; grid-template-columns: minmax(0, 1.65fr) minmax(280px, 1fr);
  gap: 18px; margin-top: 18px; align-items: start; }
.upload-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 16px; margin-top: 14px; }
.upload-form .field-full { grid-column: 1 / -1; }
.upload-form input[type="file"] { padding: 10px; background: rgba(124,58,237,.1); }
.upload-form input[type="file"]::file-selector-button {
  margin-right: 10px; padding: 6px 11px; border: 1px solid rgba(196,181,253,.3);
  border-radius: 999px; background: rgba(255,255,255,.08); color: #e9d5ff;
  font: inherit; font-size: 12.5px; font-weight: 700; cursor: pointer;
  transition: transform .16s ease, background-color .16s ease, box-shadow .16s ease; }
.upload-form input[type="file"]::file-selector-button:hover {
  background: rgba(240,171,252,.22); transform: translateY(-1px);
  box-shadow: 0 6px 14px -10px rgba(240,171,252,.9); }
.upload-form .columns { margin: 0; color: var(--muted); font-size: 11.5px;
  line-height: 1.45; overflow-wrap: anywhere; }
.upload-form .check-field, .plan-form .check-field, .auth-form .check-field {
  grid-column: 1 / -1; display: flex;
  gap: 10px; align-items: flex-start; padding: 12px 14px;
  border: 1px solid rgba(196,181,253,.26);
  border-radius: 12px; background: rgba(124,58,237,.12); font-size: 13px;
  color: #ddd0f2; }
.upload-form .check-field input, .plan-form .check-field input,
.auth-form .check-field input { width: 18px;
  height: 18px; margin: 2px 0 0; flex: 0 0 auto; accent-color: var(--accent); }
.upload-form .actions { grid-column: 1 / -1; display: flex; flex-wrap: wrap;
  gap: 10px; align-items: center; }
.upload-note { grid-column: 1 / -1; margin: 0; color: var(--muted); font-size: 12px; }
.sample-links { display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center;
  margin: 2px 0 0; font-size: 12.5px; }
.sample-links a { color: var(--accent); font-weight: 700; }
.recent-list { list-style: none; margin: 14px 0 0; padding: 0; display: grid; gap: 10px; }
.recent-list li { padding: 12px 14px; border: 1px solid var(--line);
  border-radius: 12px; background: rgba(124,58,237,.1); }
.recent-main { display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: baseline; }
.recent-main strong { word-break: break-word; }
.recent-meta { margin: 3px 0 0; color: var(--muted); font-size: 12px; }
.recent-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
  margin-top: 9px; }
.recent-empty { margin: 14px 0 0; padding: 14px;
  border: 1px dashed rgba(196,181,253,.35); border-radius: 12px;
  background: rgba(124,58,237,.1); color: var(--muted); font-size: 13.5px; }
.upload-steps { margin: 14px 0 0; padding-left: 20px; color: var(--muted);
  font-size: 13px; }
.upload-steps li { margin-bottom: 6px; }
.upload-steps strong { color: var(--ink); }
.plan-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 16px; margin-top: 14px; }
.plan-grid .field-full { grid-column: 1 / -1; }
.plan-form input, .plan-form select, .plan-form textarea { width: 100%;
  padding: 9px 11px; border: 1px solid #4c2a78; border-radius: 10px;
  background: #241041; color: var(--ink); font: inherit; font-size: 14px; }
.plan-form input:hover, .plan-form select:hover, .plan-form textarea:hover {
  border-color: #6d3aa3; }
.plan-form input:focus, .plan-form select:focus, .plan-form textarea:focus {
  outline: 3px solid rgba(192,132,252,.25); border-color: var(--accent); }
.plan-form textarea { min-height: 82px; resize: vertical; }
.plan-rows { margin-top: 14px; }
.plan-row-head, .plan-row { display: grid; gap: 8px; align-items: center; }
.cat-cols { grid-template-columns: 30px minmax(0, 2fr) minmax(0, 1fr) minmax(0, 1fr); }
.spend-cols { grid-template-columns: 30px minmax(0, 1.6fr)
  minmax(0, .9fr) minmax(0, 2fr); }
.plan-row-head { padding: 0 2px 4px; color: #b9a3d8; font-size: 10.5px;
  text-transform: uppercase; letter-spacing: .06em; font-weight: 800; }
.plan-row { margin-bottom: 7px; }
.plan-row-new { animation: row-pop .26s ease-out both; }
@keyframes row-pop {
  from { opacity: 0; transform: translateY(4px) scale(.97); }
  to { opacity: 1; transform: none; }
}
.plan-row input, .plan-row select { padding: 8px 9px; font-size: 13px; }
.row-no { color: #a28cc4; font-size: 11px; font-weight: 700;
  font-variant-numeric: tabular-nums; text-align: right; }
.plan-section-note { margin: 8px 0 0; color: var(--muted); font-size: 12px; }
.plan-add { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center;
  margin: 12px 0 0; padding: 12px 2px 0;
  border-top: 1px dashed rgba(196,181,253,.28); }
.plan-add .button { border-style: dashed; }
#categories-end, #spending-end { scroll-margin-top: 200px; }
.plan-add-button { width: 38px; height: 38px; padding: 0; font-size: 22px;
  line-height: 1; }
.plan-add-button span { display: inline-block; transform: translateY(-1px);
  transition: transform .25s ease; }
.plan-add-button:hover span { transform: translateY(-1px) rotate(90deg); }
.error-list { margin: 5px 0 0; padding-left: 18px; }
.error-list li { margin: 2px 0; }
.plan-actions { display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
  margin-top: 14px; }
.plan-cards { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.plan-meta { display: flex; flex-wrap: wrap; gap: 6px 18px; margin: 0 0 4px;
  color: var(--muted); font-size: 13px; }
.plan-meta strong { color: var(--ink); }
.method-note { margin: 10px 0 0; padding: 12px 14px; border-left: 3px solid #a78bfa;
  background: rgba(124,58,237,.12); border-radius: 0 10px 10px 0; color: #e4d8f7;
  font-size: 13.5px; }
.insight-list { margin: 8px 0 0; padding-left: 20px; color: #e4d8f7; font-size: 14px; }
.insight-list li { margin-bottom: 7px; }
.plan-tag { display: inline-block; margin-left: 7px; padding: 1px 7px;
  border-radius: 999px; background: rgba(124,58,237,.24); color: #e9d5ff;
  font-size: 10.5px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; }
.pill.warn { background: rgba(154,52,18,.28); color: #fdba74; }
.pill.neutral { background: rgba(124,58,237,.22); color: #e9d5ff; }
.banner.note { background: rgba(124,58,237,.12);
  border: 1px solid rgba(196,181,253,.24); color: #ddd0f2; }
.suggestion-list { display: grid; gap: 10px; margin: 10px 0 0; padding: 0;
  list-style: none; }
.suggestion { padding: 12px 14px; border-radius: 12px;
  border: 1px solid rgba(196,181,253,.24); background: rgba(124,58,237,.1); }
.suggestion.bad { border-color: rgba(253,164,175,.42);
  background: rgba(190,24,93,.14); }
.suggestion.warn { border-color: rgba(253,186,116,.4);
  background: rgba(154,52,18,.16); }
.suggestion.good { border-color: rgba(110,231,183,.36);
  background: rgba(6,78,59,.2); }
.suggestion h4 { margin: 0; color: #fff; font-size: 14px; }
.suggestion p { margin: 5px 0 0; color: #ddd0f2; font-size: 13px;
  line-height: 1.5; }
.coach-form { display: grid; gap: 12px; margin-top: 14px; }
.coach-question { display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-end; }
.coach-question .field { flex: 1 1 300px; }
.coach-question .button { flex: 0 0 auto; }
.coach-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.coach-chips .button { padding: 7px 12px; font-size: 12px; }
.coach-answer { margin-top: 16px; padding: 16px 18px; border-radius: 14px;
  border: 1px solid rgba(192,132,252,.32);
  background: linear-gradient(150deg, rgba(124,58,237,.2), rgba(19,7,36,.5)); }
.coach-asked { margin: 0 0 8px; color: #f0abfc; font-size: 13px; font-weight: 700; }
.coach-asked span { color: #ddd0f2; font-weight: 500; }
.coach-answer p { margin: 0 0 8px; color: #e4d8f7; font-size: 13.5px;
  line-height: 1.55; }
.coach-answer p:last-child { margin-bottom: 0; }
.coach-origin { display: inline-block; margin-bottom: 8px; padding: 2px 8px;
  border-radius: 999px; background: rgba(192,132,252,.18); color: #e9d5ff;
  font-size: 10px; font-weight: 800; letter-spacing: .08em;
  text-transform: uppercase; }
.plan-split { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr);
  gap: 18px; align-items: start; }
.receipt-wrap { position: relative; display: flex; justify-content: center;
  margin: 18px 0 8px; padding: 8px; }
.receipt { position: relative; width: min(100%, 430px); margin: 0;
  padding: 26px 24px 20px; overflow: hidden; border-radius: 18px;
  border: 1px solid rgba(216,180,254,.36); color: #f6ecff;
  background:
    radial-gradient(120% 80% at 15% 0%, rgba(217,70,239,.24), transparent 58%),
    linear-gradient(163deg, #2a0f4d 0%, #1a0833 58%, #250b46 100%);
  font-family: "Cascadia Mono", "Consolas", "SFMono-Regular", ui-monospace, monospace;
  box-shadow: 0 26px 60px -28px rgba(168,85,247,.85),
    0 0 46px rgba(192,132,252,.22), inset 0 1px 0 rgba(255,255,255,.09); }
.receipt::before { content: ""; position: absolute; inset: -40% -60%; pointer-events: none;
  background: linear-gradient(115deg, transparent 38%, rgba(255,255,255,.13) 50%,
    transparent 62%);
  transform: translateX(-55%) rotate(8deg);
  animation: receipt-sheen 8s ease-in-out infinite; }
.receipt > * { position: relative; z-index: 1; }
@keyframes receipt-sheen {
  0%, 35% { transform: translateX(-55%) rotate(8deg); opacity: 0; }
  50% { opacity: .9; }
  65%, 100% { transform: translateX(55%) rotate(8deg); opacity: 0; }
}
.receipt-stamp { position: absolute; top: 16px; right: 6px; z-index: 2;
  padding: 5px 8px; border: 1.5px solid rgba(244,114,182,.6); border-radius: 7px;
  color: #f9a8d4; font-size: 8.5px; font-weight: 700; line-height: 1.15;
  letter-spacing: .12em; text-align: center; text-transform: uppercase;
  transform: rotate(-11deg); opacity: .85; }
.receipt-head { display: grid; gap: 2px; margin-bottom: 16px; text-align: center; }
.receipt-kicker { font-size: 9.5px; letter-spacing: .28em; text-transform: uppercase;
  color: #d8b4fe; }
.receipt-title { font-size: 19px; letter-spacing: .08em; text-transform: uppercase;
  color: #fff; }
.receipt-sub { font-size: 10.5px; letter-spacing: .12em; text-transform: uppercase;
  color: #bda9dd; }
.receipt-meta { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 14px; margin: 0; font-size: 11px; }
.receipt-meta div { min-width: 0; }
.receipt-meta dt { color: #a98cc9; font-size: 8.5px; letter-spacing: .14em;
  text-transform: uppercase; }
.receipt-meta dd { margin: 1px 0 0; color: #f4e9ff; overflow-wrap: anywhere; }
.receipt-rule { height: 1px; margin: 14px 0;
  background: repeating-linear-gradient(90deg, rgba(216,180,254,.45) 0 5px,
    transparent 5px 10px); }
.receipt-lines { list-style: none; margin: 0; padding: 0; display: grid; gap: 9px; }
.receipt-lines li { display: flex; align-items: baseline; gap: 7px; font-size: 11.5px; }
.receipt-item { display: inline-flex; align-items: center; gap: 6px; min-width: 0; }
.receipt-name { color: #f4e9ff; overflow-wrap: anywhere; }
.receipt-tag { flex: 0 0 auto; padding: 0 5px; border-radius: 999px;
  background: rgba(192,132,252,.18); color: #ddc9f8; font-size: 7.5px;
  letter-spacing: .08em; text-transform: uppercase; }
.receipt-dots { flex: 1 1 16px; min-width: 12px;
  border-bottom: 1px dotted rgba(196,181,253,.4); transform: translateY(-3px); }
.receipt-share { flex: 0 0 auto; color: #c4b5fd; font-size: 10px;
  font-variant-numeric: tabular-nums; }
.receipt-amount { flex: 0 0 auto; min-width: 66px; text-align: right; color: #fff;
  font-size: 12px; font-weight: 700; font-variant-numeric: tabular-nums; }
.receipt-totals { margin: 0; display: grid; gap: 5px; font-size: 11.5px; }
.receipt-totals div { display: flex; justify-content: space-between; gap: 12px; }
.receipt-totals dt { color: #b9a4d8; }
.receipt-totals dd { margin: 0; color: #f4e9ff; font-variant-numeric: tabular-nums; }
.receipt-totals .receipt-balance { margin-top: 4px; padding-top: 7px;
  border-top: 1px dashed rgba(216,180,254,.35); font-size: 13px; }
.receipt-totals .receipt-balance dt { color: #f0abfc; font-weight: 700; }
.receipt-totals .receipt-balance dd { color: #fff; font-weight: 700; }
.receipt-foot { margin: 14px 0 10px; text-align: center; color: #a98cc9;
  font-size: 8.5px; line-height: 1.5; letter-spacing: .06em; text-transform: uppercase; }
.receipt-barcode { width: 78%; height: 30px; margin: 0 auto; border-radius: 2px;
  opacity: .8;
  background: repeating-linear-gradient(90deg, rgba(244,233,255,.85) 0 2px,
    transparent 2px 4px, rgba(244,233,255,.6) 4px 7px, transparent 7px 10px,
    rgba(244,233,255,.9) 10px 11px, transparent 11px 14px); }
.receipt-code { margin: 5px 0 0; text-align: center; color: #a98cc9;
  font-size: 8px; letter-spacing: .18em; }
.account-bar { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end;
  gap: 8px 16px; margin: 0 0 12px; padding: 8px 10px 8px 16px; border-radius: 999px;
  border: 1px solid rgba(196,181,253,.18); background: rgba(19,7,36,.66);
  backdrop-filter: blur(12px); font-size: 12.5px; color: var(--muted); }
.account-bar .account-mode { display: inline-flex; align-items: center; gap: 8px; }
.account-bar strong { color: var(--ink); }
.account-bar form { margin: 0; display: inline-flex; }
.account-links { display: inline-flex; align-items: center; gap: 14px; }
.account-links a { color: #e9d5ff; font-weight: 700; text-decoration: none; }
.account-links a:hover, .account-links a:focus-visible { text-decoration: underline; }
.account-links .account-cta { padding: 5px 13px; border-radius: 999px;
  background: linear-gradient(100deg, #7c3aed, #c026d3); color: #fff;
  transition: transform .18s ease, box-shadow .18s ease; }
.account-links .account-cta:hover { text-decoration: none; transform: translateY(-1px);
  box-shadow: 0 8px 18px -10px rgba(192,38,211,.9); }
.account-signout { padding: 5px 13px; border-radius: 999px;
  border: 1px solid rgba(196,181,253,.35); background: rgba(255,255,255,.06);
  color: #e9d5ff; font: inherit; font-size: 12px; font-weight: 700; cursor: pointer; }
.account-signout:hover { background: rgba(255,255,255,.14); }
.auth-shell { max-width: 980px; padding-top: 16px; min-height: calc(100vh - 102px);
  display: flex; flex-direction: column; justify-content: center; }
.auth-grid { display: grid; grid-template-columns: minmax(0, 1.06fr) minmax(0, .94fr);
  gap: 20px; align-items: start; }
.auth-card { padding: 32px 32px 30px; }
.auth-card .eyebrow { margin-bottom: 8px; }
.auth-card h1 { margin: 0 0 10px; font-size: clamp(28px, 3.6vw, 38px);
  line-height: 1.08; letter-spacing: -.03em; color: #fff; }
.auth-card h1 span { background: linear-gradient(100deg, #e9d5ff, #f0abfc 48%, #c4b5fd);
  -webkit-background-clip: text; background-clip: text; color: transparent; }
.auth-card .lead { margin-bottom: 16px; }
.auth-form { display: grid; gap: 14px; margin: 16px 0 0; }
.auth-form .field label { font-size: 11.5px; font-weight: 700;
  text-transform: uppercase; letter-spacing: .06em; color: #cbb6ea; }
.auth-form .field input { padding: 10px 12px; }
.auth-form .field-full { grid-column: 1 / -1; }
.auth-form .auth-submit { width: 100%; margin-top: 4px; padding: 11px 18px;
  font-size: 14px; }
.auth-alternate { margin: 16px 0 0; text-align: center; color: var(--muted);
  font-size: 13px; }
.auth-alternate a { color: var(--accent); font-weight: 700; }
.auth-alternate a:hover { color: #fff; }
.auth-note { margin: 16px 0 0; padding: 12px 14px; border-radius: 12px;
  border: 1px solid rgba(196,181,253,.22); background: rgba(124,58,237,.12);
  color: #ddd0f2; font-size: 12.5px; }
.auth-note strong { color: #f5d0fe; }
.auth-side { padding: 28px 26px; }
.auth-side h2 { margin: 0 0 8px; font-size: 20px; }
.auth-badge { display: inline-flex; align-items: center; gap: 8px; padding: 4px 11px;
  border-radius: 999px; background: rgba(124,58,237,.24); color: #e9d5ff;
  font-size: 11px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; }
.auth-steps { list-style: none; margin: 16px 0 0; padding: 0; counter-reset: auth-step;
  display: grid; gap: 12px; }
.auth-steps li { position: relative; padding-left: 34px; color: var(--muted);
  font-size: 13.5px; }
.auth-steps li::before { counter-increment: auth-step; content: counter(auth-step);
  position: absolute; left: 0; top: 1px; width: 22px; height: 22px; border-radius: 50%;
  display: grid; place-items: center; background: rgba(192,132,252,.2); color: #f0abfc;
  font-size: 11px; font-weight: 800; }
.auth-steps strong { color: var(--ink); }
.auth-side .sample-links { margin-top: 18px; }
.legal-shell { max-width: 880px; }
.legal-body h1 { margin-bottom: 4px; }
.legal-body h2 { margin: 26px 0 8px; font-size: 18px; }
.legal-body p, .legal-body li { color: var(--muted); font-size: 13.5px;
  line-height: 1.65; }
.legal-body strong { color: var(--ink); }
.legal-body ul { margin: 8px 0 12px; padding-left: 22px; display: grid; gap: 6px; }
.legal-version { font-size: 12px; letter-spacing: .03em; text-transform: uppercase;
  color: #d8b4fe; }
.legal-nav { display: flex; flex-wrap: wrap; gap: 14px; margin: 0 0 14px; }
.legal-nav a { color: #e9d5ff; font-size: 13px; font-weight: 700; }
.legal-foot { margin-top: 26px; padding-top: 12px; border-top: 1px solid var(--line);
  font-size: 12px; }
.account-shell { max-width: 960px; }
.account-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px; }
.account-grid .panel { margin: 0; }
.account-facts { display: grid; gap: 8px; margin: 14px 0; }
.account-facts div { display: flex; justify-content: space-between; gap: 12px;
  padding-bottom: 7px; border-bottom: 1px dashed var(--line); }
.account-facts dt { color: var(--muted); font-size: 12.5px; }
.account-facts dd { margin: 0; text-align: right; font-weight: 700; font-size: 13px;
  overflow-wrap: anywhere; }
.account-code { display: block; margin: 12px 0; padding: 12px 14px; border-radius: 12px;
  background: rgba(124,58,237,.2); border: 1px solid rgba(196,181,253,.3);
  color: #f5e9ff; font-size: 18px; font-weight: 800; letter-spacing: .08em;
  text-align: center; overflow-wrap: anywhere; }
.danger-zone { border-color: rgba(248,113,113,.4); }
.plan-tag.near { background: rgba(251,191,36,.18); border-color: rgba(251,191,36,.4);
  color: #fde68a; }
.plan-export { margin-top: 14px; display: flex; justify-content: flex-end; }
@media (max-width: 760px) {
  .account-grid { grid-template-columns: 1fr; }
}
@media (max-width: 900px) {
  .auth-grid { grid-template-columns: 1fr; }
  .plan-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .plan-split { grid-template-columns: 1fr; }
  .upload-grid { grid-template-columns: 1fr; }
  .filters { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .field-search { grid-column: span 2; }
  .filters .actions { grid-column: span 2; }
  .dash-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .split { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
  .upload-form { grid-template-columns: 1fr; }
  .upload-form .field-full { grid-column: auto; }
  .upload-form .check-field { grid-column: auto; }
  .upload-form .actions { grid-column: auto; }
  .upload-note { grid-column: auto; }
  .plan-grid { grid-template-columns: 1fr; }
  .plan-grid .field-full { grid-column: auto; }
  .plan-form .check-field { grid-column: auto; }
  .plan-row-head { display: none; }
  .cat-cols, .spend-cols { grid-template-columns: 1fr; }
  .plan-row { padding: 10px 12px; border: 1px solid var(--line);
    border-radius: 12px; background: #241041; margin-bottom: 10px; }
  .plan-row .row-no { display: none; }
  .plan-row input, .plan-row select { font-size: 14px; }
  .plan-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .filters { grid-template-columns: 1fr; }
  .field-search { grid-column: auto; }
  .filters .actions { grid-column: auto; }
  .dash-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .resultbar .button { width: 100%; }
  .resultbar { align-items: flex-start; }
  .receipt-wrap { padding: 2px; }
  .receipt { padding: 22px 16px 16px; }
  .receipt-meta { grid-template-columns: 1fr; gap: 6px; }
  .receipt-lines li { font-size: 11px; gap: 5px; }
  .receipt-tag { display: none; }
  .receipt-amount { min-width: 58px; }
  .receipt-stamp { top: 12px; right: 2px; }
  .account-bar { border-radius: 16px; justify-content: space-between; }
  .auth-card, .auth-side { padding: 22px 18px; }
}
@media (max-width: 420px) {
  .dash-cards, .plan-cards { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) {
  .button, button, .account-links .account-cta, .plan-add-button span,
  .upload-form input[type="file"]::file-selector-button,
  .plan-row-new { animation: none; transition: none; }
  .button::after, button::after { display: none; }
  .button:hover, .button:active, button:hover, button:active,
  .account-links .account-cta:hover { transform: none; }
}
@media print {
  .account-bar, .auth-side { display: none !important; }
  .filters, .pager, .hero-actions, .resultbar .button, .active-filters { display: none !important; }
  .receipt-wrap { display: block; padding: 0; }
  .receipt { width: 100%; max-width: 430px; margin: 0 auto; background: #fff !important;
    color: #111 !important; border: 1px dashed #444; box-shadow: none; }
  .receipt * { color: #111 !important; border-color: #999 !important;
    background: transparent !important; }
  .receipt::before, .receipt-stamp, .receipt-barcode { display: none; }
  .receipt-totals .receipt-balance { border-top: 1px dashed #444; }
}
"""


@dataclass(frozen=True)
class FilterOptions:
    students: list[dict]
    categories: list[str]
    payments: list[str]
    first_date: str
    last_date: str


@dataclass(frozen=True)
class Filters:
    date_from: str
    date_to: str
    student_id: str = ""
    category: str = ""
    payment_method: str = ""
    search: str = ""
    flag: str = "all"
    sort: str = "newest"
    per_page: int = 25
    page: int = 1
    analysis: str = ""

    @property
    def anomalies_only(self) -> bool:
        return self.flag == "anomalies"

    def to_query(self, page: int | None = None) -> dict[str, str]:
        query = {"from": self.date_from, "to": self.date_to}
        if self.analysis:
            query["analysis"] = self.analysis
        if self.student_id:
            query["student"] = self.student_id
        if self.category:
            query["category"] = self.category
        if self.payment_method:
            query["payment"] = self.payment_method
        if self.search:
            query["q"] = self.search
        if self.flag != "all":
            query["flag"] = self.flag
        if self.sort != "newest":
            query["sort"] = self.sort
        if self.per_page != 25:
            query["per_page"] = str(self.per_page)
        target_page = self.page if page is None else page
        if target_page > 1:
            query["page"] = str(target_page)
        return query


@dataclass
class DashboardData:
    kpis: dict
    months: list[dict]
    categories: list[dict]
    merchants: list[dict]
    payments: list[dict]
    transactions: list[dict]
    page: int
    page_count: int
    first_row: int
    last_row: int


def _first(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key)
    return values[0].strip() if values else ""


def _form_row_count(
    form: dict[str, list[str]], key: str, *, default: int, maximum: int
) -> int:
    try:
        value = int(_first(form, key))
    except ValueError:
        return default
    return min(max(value, default), maximum)


def _valid_date(value: str) -> bool:
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _valid_int(value: str, *, minimum: int, maximum: int | None = None) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number < minimum:
        return None
    if maximum is not None and number > maximum:
        return None
    return number


def _like_pattern(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def escape_attr(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


_CSRF_VALUE: contextvars.ContextVar[str] = contextvars.ContextVar(
    "planit_csrf", default=""
)


def csrf_field() -> str:
    """Hidden field binding an authenticated form to the current session."""
    token = _CSRF_VALUE.get()
    if not token:
        return ""
    return (
        '<input type="hidden" name="csrf" value="' + escape_attr(token) + '">'
    )


def _document(
    title: str,
    body: str,
    *,
    skip_href: str | None = "#summary",
    skip_label: str = "Skip to results",
    extra_head: str = "",
) -> str:
    skip = (
        f'<a class="skip" href="{escape_attr(skip_href)}">{escape_attr(skip_label)}</a>\n'
        if skip_href
        else ""
    )
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{escape_attr(title)}</title>\n"
        "<meta name=\"description\" content=\"Plan It budgeting and spending "
        "analysis workspace.\">\n"
        "<link rel=\"icon\" href=\"data:,\">\n"
        f"{extra_head}"
        f"<style>{BASE_CSS}{_DASH_CSS}</style>\n</head>\n<body>\n"
        f"{skip}"
        f"{scene_markup()}\n"
        f"{body}</body>\n</html>\n"
    )


def _error_document(
    title: str,
    message: str,
    *,
    action_href: str = "/",
    action_label: str = "Back to the dashboard",
    eyebrow: str = "Spending explorer",
) -> str:
    body = f"""
<main class="shell">
  <section class="panel error-page">
    <p class="eyebrow">{escape_attr(eyebrow)}</p>
    <h2>{escape_attr(title)}</h2>
    <p>{escape_attr(message)}</p>
    <p><a class="button primary" href="{escape_attr(action_href)}">{escape_attr(action_label)}</a></p>
  </section>
</main>
"""
    return _document(f"{title} · Student Spending", body, skip_href=None)


def _safe_next(value: str, fallback: str = "/plan") -> str:
    """Only allow a same-origin path the sign-in flow knows about."""
    if not value or len(value) > 200:
        return fallback
    if not value.startswith("/") or value.startswith("//"):
        return fallback
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return fallback
    if parsed.path not in {"/", "/plan", "/upload", "/account"}:
        return fallback
    query = urllib.parse.urlencode(
        urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    )
    return parsed.path + (f"?{query}" if query else "")


def _auth_href(path: str, next_path: str) -> str:
    return f"{path}?{urllib.parse.urlencode({'next': next_path})}"


def _legal_links() -> str:
    return (
        '<span class="legal-links"><a href="/privacy">Privacy</a>'
        '<a href="/terms">Terms</a></span>'
    )


def _account_bar(account: Account | None) -> str:
    if account is None:
        return (
            '<div class="account-bar">'
            '<span class="account-mode"><span class="status-dot"></span>'
            " Sample dashboard &middot; public data</span>"
            '<span class="account-links"><a href="/login">Sign in</a>'
            '<a class="account-cta" href="/signup">Create account</a></span>'
            "</div>"
        )
    return (
        '<div class="account-bar">'
        f'<span class="account-mode">Signed in as '
        f"<strong>{escape_attr(account.display_name)}</strong></span>"
        '<span class="account-links"><a href="/account">Account</a>'
        '<form method="post" action="/logout">'
        f"{csrf_field()}"
        '<button class="account-signout" type="submit">Sign out</button>'
        "</form></span></div>"
    )


def _auth_side(*, signed_up: bool) -> str:
    sample = (
        '<p class="sample-links"><span>The synthetic sample dashboard stays open:</span>'
        ' <a href="/">browse the sample data</a></p>'
    )
    return f"""
  <aside class="panel auth-side" aria-labelledby="auth-side-title">
    <span class="auth-badge">Local accounts</span>
    <h2 id="auth-side-title">What an account unlocks</h2>
    <p class="lead">Accounts gate the personal tools. Your figures stay on this
      server, are scoped to your account and are never sold or sent to advertisers.</p>
    <ol class="auth-steps">
      <li><strong>Money planner</strong> &mdash; your categories, spending entries and
        the printable receipt.</li>
      <li><strong>CSV uploads</strong> &mdash; validate one transactions CSV and explore
        the isolated dashboard it builds.</li>
      <li><strong>No third-party tracking</strong> &mdash; passwords are kept as salted
        scrypt hashes; sessions end after {SESSION_SECONDS // 3600} hours.</li>
    </ol>
    {sample if not signed_up else ""}
  </aside>"""


def render_login_page(
    *,
    email: str = "",
    errors: list[str] | None = None,
    next_path: str = "/plan",
    notice: str = "",
) -> str:
    notice_html = (
        f'<div class="banner note" role="status">{escape_attr(notice)}</div>'
        if notice
        else ""
    )
    body = f"""
<main class="shell auth-shell">
  <div class="auth-grid">
    <section class="panel auth-card" aria-labelledby="login-title">
      <p class="eyebrow">Welcome back</p>
      <h1 id="login-title">Sign in to <span>plan your money</span></h1>
      <p class="lead">Use the account you created on this service. No email is
        sent; if you saved your one-time recovery code you can reset the password.</p>
      {notice_html}
      {_plan_error_banner(errors or [])}
      <form class="auth-form" method="post" action="/login" accept-charset="utf-8">
        <input type="hidden" name="next" value="{escape_attr(next_path)}">
        <div class="field">
          <label for="login-email">Email</label>
          <input id="login-email" name="email" type="email" required
            maxlength="{MAX_EMAIL_LENGTH}" value="{escape_attr(email)}"
            autocomplete="username" spellcheck="false">
        </div>
        <div class="field">
          <label for="login-password">Password</label>
          <input id="login-password" name="password" type="password" required
            maxlength="{MAX_PASSWORD_LENGTH}" autocomplete="current-password">
        </div>
        <button class="button primary auth-submit" type="submit">Sign in</button>
      </form>
      <p class="auth-alternate">Forgot the password?
        <a href="/reset">Use a recovery code</a>
      </p>
      <p class="auth-alternate">New here?
        <a href="{escape_attr(_auth_href('/signup', next_path))}">Create an account</a>
      </p>
      <p class="auth-note"><strong>Local account.</strong> Never reuse a real password
        or enter bank, card or payment credentials. Account records stay on the
        server that runs this service.</p>
    </section>
    {_auth_side(signed_up=False)}
  </div>
</main>
"""
    return _document("Sign in · Student Spending Analytics", body, skip_href=None)


def render_signup_page(
    *,
    display_name: str = "",
    email: str = "",
    errors: list[str] | None = None,
    next_path: str = "/plan",
) -> str:
    body = f"""
<main class="shell auth-shell">
  <div class="auth-grid">
    <section class="panel auth-card" aria-labelledby="signup-title">
      <p class="eyebrow">Create an account</p>
      <h1 id="signup-title">Make a <span>local account</span></h1>
      <p class="lead">A display name, an email and a password are enough. No email is
        sent, so use an address you are comfortable storing on this service.</p>
      {_plan_error_banner(errors or [])}
      <form class="auth-form" method="post" action="/signup" accept-charset="utf-8">
        <input type="hidden" name="next" value="{escape_attr(next_path)}">
        <div class="field">
          <label for="signup-name">Display name</label>
          <input id="signup-name" name="display_name" type="text" required
            maxlength="{MAX_DISPLAY_NAME_LENGTH}" value="{escape_attr(display_name)}"
            placeholder="A nickname is fine" autocomplete="nickname">
        </div>
        <div class="field">
          <label for="signup-email">Email</label>
          <input id="signup-email" name="email" type="email" required
            maxlength="{MAX_EMAIL_LENGTH}" value="{escape_attr(email)}"
            autocomplete="username" spellcheck="false">
        </div>
        <div class="field">
          <label for="signup-password">Password</label>
          <input id="signup-password" name="password" type="password" required
            minlength="{MIN_PASSWORD_LENGTH}" maxlength="{MAX_PASSWORD_LENGTH}"
            autocomplete="new-password"
            aria-describedby="signup-password-hint">
          <span class="section-note" id="signup-password-hint">At least
            {MIN_PASSWORD_LENGTH} characters, including a letter and a number.</span>
        </div>
        <div class="field">
          <label for="signup-confirm">Confirm password</label>
          <input id="signup-confirm" name="confirm" type="password" required
            minlength="{MIN_PASSWORD_LENGTH}" maxlength="{MAX_PASSWORD_LENGTH}"
            autocomplete="new-password">
        </div>
        <label class="check-field">
          <input type="checkbox" name="privacy_ack" value="yes" required>
          <span><strong>I agree to the data practices described here.</strong> I have
            read the <a href="/privacy">Privacy notice</a> and
            <a href="/terms">Terms of use</a> (version {legal.POLICY_VERSION}). I
            understand the time and version of this consent are recorded, and that I
            can withdraw it by deleting my account.</span>
        </label>
        <button class="button primary auth-submit" type="submit">Create account</button>
      </form>
      <p class="auth-alternate">Already have one?
        <a href="{escape_attr(_auth_href('/login', next_path))}">Sign in</a>
      </p>
      <p class="auth-note"><strong>Your account.</strong> Use your own name and email.
        Never enter card numbers, bank or mobile-money PINs or other payment
        credentials. The password is saved
        only as a salted scrypt hash, and the session cookie is HttpOnly and expires after
        {SESSION_SECONDS // 3600} hours. A one-time recovery code is shown after
        sign-up so you can reset the password without email.</p>
    </section>
    {_auth_side(signed_up=True)}
  </div>
</main>
"""
    return _document("Create account · Student Spending Analytics", body, skip_href=None)


def render_reset_page(
    *,
    email: str = "",
    errors: list[str] | None = None,
) -> str:
    body = f"""
<main class="shell auth-shell">
  <div class="auth-grid">
    <section class="panel auth-card" aria-labelledby="reset-title">
      <p class="eyebrow">Account recovery</p>
      <h1 id="reset-title">Reset with a <span>recovery code</span></h1>
      <p class="lead">No email is sent. Enter the one-time code shown when you created
        the account, or when you last generated a new one.</p>
      {_plan_error_banner(errors or [])}
      <form class="auth-form" method="post" action="/reset" accept-charset="utf-8">
        <div class="field">
          <label for="reset-email">Email</label>
          <input id="reset-email" name="email" type="email" required
            maxlength="{MAX_EMAIL_LENGTH}" value="{escape_attr(email)}"
            autocomplete="username" spellcheck="false">
        </div>
        <div class="field">
          <label for="reset-code">Recovery code</label>
          <input id="reset-code" name="recovery_code" type="text" required
            maxlength="40" autocomplete="one-time-code" spellcheck="false"
            placeholder="XXXX-XXXX-XXXX-XXXX">
        </div>
        <div class="field">
          <label for="reset-password">New password</label>
          <input id="reset-password" name="password" type="password" required
            minlength="{MIN_PASSWORD_LENGTH}" maxlength="{MAX_PASSWORD_LENGTH}"
            autocomplete="new-password">
        </div>
        <div class="field">
          <label for="reset-confirm">Confirm new password</label>
          <input id="reset-confirm" name="confirm" type="password" required
            minlength="{MIN_PASSWORD_LENGTH}" maxlength="{MAX_PASSWORD_LENGTH}"
            autocomplete="new-password">
        </div>
        <button class="button primary auth-submit" type="submit">Reset password</button>
      </form>
      <p class="auth-alternate">Remembered it?
        <a href="/login">Back to sign in</a>
      </p>
      <p class="auth-note">The code is single-use and is replaced when you generate a
        new one from the account page. A successful reset signs out every session.</p>
    </section>
    {_auth_side(signed_up=False)}
  </div>
</main>
"""
    return _document("Reset password · Plan It", body, skip_href=None)


def render_account_page(
    account: Account,
    *,
    new_code: str = "",
    errors: list[str] | None = None,
    notice: str = "",
) -> str:
    consent_current = (
        account.consent_at is not None
        and account.policy_version == legal.POLICY_VERSION
    )
    consent_value = (
        f"{escape_attr(account.consent_at)} · version "
        f"{escape_attr(account.policy_version or 'unknown')}"
        if account.consent_at
        else "Not recorded"
    )
    code_html = (
        f'<p class="banner good" role="status"><strong>Save this recovery code now.'
        f'</strong> It is shown once and cannot be retrieved again.</p>'
        f'<code class="account-code">{escape_attr(new_code)}</code>'
        if new_code
        else ""
    )
    notice_html = (
        f'<p class="banner good" role="status">{escape_attr(notice)}</p>'
        if notice
        else ""
    )
    consent_form = (
        f"""
      <form class="auth-form" method="post" action="/account/consent">
        {csrf_field()}
        <label class="check-field">
          <input type="checkbox" name="privacy_ack" value="yes" required>
          <span>I have read the <a href="/privacy">Privacy notice</a> and
            <a href="/terms">Terms of use</a> and agree to this version
            ({legal.POLICY_VERSION}).</span>
        </label>
        <button class="button primary" type="submit">Record consent</button>
      </form>"""
        if not consent_current
        else "<p class=\"section-note\">Consent is current for this policy version. "
             "Withdraw it by deleting the account below.</p>"
    )
    recovery_note = (
        "A recovery code is set. Generating a new one replaces the old code."
        if account.recovery_configured
        else "No recovery code is set. Generate one now so you can reset the password."
    )
    body = f"""
<main class="shell account-shell">
  {_account_bar(account)}
  <header class="hero dash-hero">
    <p class="eyebrow">Plan It &middot; account</p>
    <h1>Your <span>account</span></h1>
    <p class="lede">Manage the local identity that unlocks the money planner and
      uploads. Password re-entry is required for export, recovery and
      deletion.</p>
    <div class="hero-actions">
      <a class="button primary" href="/plan">Open the planner</a>
      <a class="button ghost" href="/upload">Open uploads</a>
    </div>
  </header>
  {code_html}
  {notice_html}
  {_plan_error_banner(errors or [])}
  <section class="panel" aria-labelledby="account-facts-title">
    <p class="eyebrow">Identity</p>
    <h2 id="account-facts-title">Account details</h2>
    <dl class="account-facts">
      <div><dt>Display name</dt><dd>{escape_attr(account.display_name)}</dd></div>
      <div><dt>Email</dt><dd>{escape_attr(account.email)}</dd></div>
      <div><dt>Created</dt><dd>{escape_attr(account.created_at)}</dd></div>
      <div><dt>Privacy consent</dt><dd>{consent_value}</dd></div>
      <div><dt>Recovery code</dt><dd>{"Set" if account.recovery_configured else "Not set"}</dd></div>
    </dl>
  </section>
  <div class="account-grid">
    <section class="panel" aria-labelledby="account-consent-title">
      <p class="eyebrow">Consent</p>
      <h2 id="account-consent-title">Privacy choices</h2>
      <p class="section-note">The timestamp and policy version are recorded with the
        account. Withdrawal means deleting the account and its uploads.
        {escape_attr(legal.DRAFT_NOTICE)}</p>
      {consent_form}
    </section>
    <section class="panel" aria-labelledby="account-recovery-title">
      <p class="eyebrow">Recovery</p>
      <h2 id="account-recovery-title">Recovery code</h2>
      <p class="section-note">{recovery_note}</p>
      <form class="auth-form" method="post" action="/account/recovery">
        {csrf_field()}
        <div class="field">
          <label for="recovery-password">Current password</label>
          <input id="recovery-password" name="current_password" type="password"
            required maxlength="{MAX_PASSWORD_LENGTH}" autocomplete="current-password">
        </div>
        <button class="button ghost" type="submit">Generate a new code</button>
      </form>
    </section>
    <section class="panel" aria-labelledby="account-password-title">
      <p class="eyebrow">Password</p>
      <h2 id="account-password-title">Change password</h2>
      <p class="section-note">Changing the password signs out every session,
        including this one.</p>
      <form class="auth-form" method="post" action="/account/password">
        {csrf_field()}
        <div class="field">
          <label for="password-current">Current password</label>
          <input id="password-current" name="current_password" type="password"
            required maxlength="{MAX_PASSWORD_LENGTH}" autocomplete="current-password">
        </div>
        <div class="field">
          <label for="password-new">New password</label>
          <input id="password-new" name="new_password" type="password" required
            minlength="{MIN_PASSWORD_LENGTH}" maxlength="{MAX_PASSWORD_LENGTH}"
            autocomplete="new-password">
        </div>
        <div class="field">
          <label for="password-confirm">Confirm new password</label>
          <input id="password-confirm" name="confirm" type="password" required
            minlength="{MIN_PASSWORD_LENGTH}" maxlength="{MAX_PASSWORD_LENGTH}"
            autocomplete="new-password">
        </div>
        <button class="button primary" type="submit">Change password</button>
      </form>
    </section>
    <section class="panel" aria-labelledby="account-export-title">
      <p class="eyebrow">Your data</p>
      <h2 id="account-export-title">Export account data</h2>
      <p class="section-note">Downloads a JSON file with the account record, consent
        and upload metadata. It never includes the password or recovery-code hash.
        Plans are not stored, so there is no plan history to export.</p>
      <form class="auth-form" method="post" action="/account/export">
        {csrf_field()}
        <div class="field">
          <label for="export-password">Password</label>
          <input id="export-password" name="password" type="password" required
            maxlength="{MAX_PASSWORD_LENGTH}" autocomplete="current-password">
        </div>
        <button class="button ghost" type="submit">Download JSON</button>
      </form>
    </section>
  </div>
  <section class="panel danger-zone" aria-labelledby="account-delete-title">
    <p class="eyebrow">Danger zone</p>
    <h2 id="account-delete-title">Withdraw consent and delete account</h2>
    <p class="lead">This removes the account, every session and every uploaded
      analysis owned by the account. It cannot be undone.</p>
    <form class="auth-form" method="post" action="/account/delete">
      {csrf_field()}
      <div class="field">
        <label for="delete-password">Password</label>
        <input id="delete-password" name="password" type="password" required
          maxlength="{MAX_PASSWORD_LENGTH}" autocomplete="current-password">
      </div>
      <label class="check-field">
        <input type="checkbox" name="confirm_delete" value="yes" required>
        <span>I understand this permanently deletes the account and its uploads.</span>
      </label>
      <button class="button ghost danger" type="submit">Delete my account</button>
    </form>
  </section>
  <footer class="panel footer">
    <p><strong>Your data.</strong> Account details and uploads stay on the
      operator's server and are never sold. {escape_attr(legal.DISCLAIMER)}</p>
    <div class="footer-links">{_legal_links()}<a class="totop" href="/">Dashboard</a></div>
  </footer>
</main>
"""
    return _document("Account · Plan It", body, skip_href=None)


def render_delete_analysis_page(analysis: AnalysisWorkspace) -> str:
    body = f"""
<main class="shell">
  <section class="panel error-page" aria-labelledby="delete-analysis-title">
    <p class="eyebrow">Delete analysis</p>
    <h2 id="delete-analysis-title">Delete {escape_attr(analysis.title)}?</h2>
    <p>This removes the uploaded CSV copy, the isolated SQLite warehouse and the
      report for <code>{escape_attr(analysis.analysis_id)}</code>. The account and
      the committed sample warehouse are not affected.</p>
    <p class="banner bad" role="alert"><strong>This cannot be undone.</strong></p>
    <form method="post" action="/delete-analysis">
      {csrf_field()}
      <input type="hidden" name="analysis_id" value="{escape_attr(analysis.analysis_id)}">
      <div class="plan-actions">
        <button class="button ghost danger" type="submit">Delete this analysis</button>
        <a class="button primary" href="/upload">Keep it</a>
      </div>
    </form>
  </section>
</main>
"""
    return _document("Delete analysis · Plan It", body, skip_href=None)


def render_legal_page(title: str, body: str) -> str:
    return _document(f"{title} · Plan It", body)


def load_options(connection: sqlite3.Connection) -> FilterOptions:
    students = [
        dict(row)
        for row in connection.execute(
            "SELECT student_id, profile_label FROM students "
            "ORDER BY profile_label, student_id"
        )
    ]
    categories = [
        str(row[0])
        for row in connection.execute("SELECT category FROM categories ORDER BY category")
    ]
    payments = [
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT payment_method FROM v_transactions ORDER BY 1"
        )
    ]
    bounds = connection.execute(
        "SELECT MIN(transaction_date), MAX(transaction_date) FROM transactions"
    ).fetchone()
    return FilterOptions(
        students=students,
        categories=categories,
        payments=payments,
        first_date=bounds[0] or "",
        last_date=bounds[1] or "",
    )


def parse_filters(query: dict[str, list[str]], options: FilterOptions) -> tuple[Filters, list[str]]:
    errors: list[str] = []

    date_from = _first(query, "from") or options.first_date
    date_to = _first(query, "to") or options.last_date
    if date_from and not _valid_date(date_from):
        errors.append("The start date must be a real date in YYYY-MM-DD form.")
        date_from = options.first_date
    if date_to and not _valid_date(date_to):
        errors.append("The end date must be a real date in YYYY-MM-DD form.")
        date_to = options.last_date
    if date_from and date_to and date_from > date_to:
        errors.append("The start date must not be after the end date.")
        date_from, date_to = options.first_date, options.last_date

    student_id = _first(query, "student")
    known_students = {str(student["student_id"]) for student in options.students}
    if student_id and student_id not in known_students:
        errors.append("That student is not in the warehouse.")
        student_id = ""

    category = _first(query, "category")
    if category and category not in options.categories:
        errors.append("That category is not in the warehouse.")
        category = ""

    payment_method = _first(query, "payment")
    if payment_method and payment_method not in options.payments:
        errors.append("That payment method is not in the warehouse.")
        payment_method = ""

    search = _first(query, "q")
    if len(search) > SEARCH_LIMIT:
        errors.append(f"Search text was shortened to {SEARCH_LIMIT} characters.")
        search = search[:SEARCH_LIMIT]

    flag = _first(query, "flag") or "all"
    if flag not in FLAG_CHOICES:
        errors.append("The review filter must be 'all' or 'anomalies'.")
        flag = "all"

    sort = _first(query, "sort") or "newest"
    if sort not in SORT_CHOICES:
        errors.append("That sort order is not available.")
        sort = "newest"

    raw_per_page = _first(query, "per_page")
    per_page = 25
    if raw_per_page:
        parsed_per_page = _valid_int(raw_per_page, minimum=1)
        if parsed_per_page in PER_PAGE_CHOICES:
            per_page = parsed_per_page
        else:
            errors.append("Rows per page must be 25, 50 or 100.")
    raw_page = _first(query, "page")
    page = 1
    if raw_page:
        parsed_page = _valid_int(raw_page, minimum=1)
        if parsed_page is None:
            errors.append("The page number must be a whole number of 1 or more.")
        else:
            page = parsed_page

    return (
        Filters(
            date_from=date_from,
            date_to=date_to,
            student_id=student_id,
            category=category,
            payment_method=payment_method,
            search=search,
            flag=flag,
            sort=sort,
            per_page=per_page,
            page=page,
        ),
        errors,
    )


def build_where(filters: Filters) -> tuple[str, list[object]]:
    clauses: list[str] = []
    params: list[object] = []
    if filters.date_from:
        clauses.append("transaction_date >= ?")
        params.append(filters.date_from)
    if filters.date_to:
        clauses.append("transaction_date <= ?")
        params.append(filters.date_to)
    if filters.student_id:
        clauses.append("student_id = ?")
        params.append(filters.student_id)
    if filters.category:
        clauses.append("category = ?")
        params.append(filters.category)
    if filters.payment_method:
        clauses.append("payment_method = ?")
        params.append(filters.payment_method)
    if filters.anomalies_only:
        clauses.append("is_anomaly = 1")
    if filters.search:
        pattern = _like_pattern(filters.search)
        clauses.append(
            "(merchant LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\')"
        )
        params.extend([pattern, pattern])
    if not clauses:
        return "1 = 1", params
    return " AND ".join(clauses), params


def load_dashboard(connection: sqlite3.Connection, filters: Filters) -> DashboardData:
    where, params = build_where(filters)
    kpis = dict(
        connection.execute(
            f"""
            SELECT COUNT(*)                                  AS transaction_count,
                   COUNT(DISTINCT student_id)                AS student_count,
                   COALESCE(SUM(amount_cents), 0)            AS total_cents,
                   ROUND(COALESCE(SUM(amount_cents), 0) / 100.0, 2) AS total_kes,
                   ROUND(COALESCE(AVG(amount_cents), 0) / 100.0, 2) AS avg_transaction_kes,
                   COALESCE(SUM(is_anomaly), 0)              AS flagged_count,
                   MIN(transaction_date)                     AS first_date,
                   MAX(transaction_date)                     AS last_date,
                   COALESCE(CAST(julianday(MAX(transaction_date))
                             - julianday(MIN(transaction_date)) + 1 AS INTEGER), 0)
                                                             AS days_covered,
                   COALESCE(ROUND((SUM(amount_cents) / 100.0)
                             / (julianday(MAX(transaction_date))
                                - julianday(MIN(transaction_date)) + 1), 2), 0)
                                                             AS avg_daily_kes
            FROM v_transactions
            WHERE {where}
            """,
            params,
        ).fetchone()
    )

    months = [
        dict(row)
        for row in connection.execute(
            f"""
            SELECT transaction_month,
                   COUNT(DISTINCT student_id) AS active_students,
                   COUNT(*)                  AS transaction_count,
                   SUM(amount_cents) / 100.0 AS total_kes
            FROM v_transactions
            WHERE {where}
            GROUP BY transaction_month
            ORDER BY transaction_month
            """,
            params,
        )
    ]
    categories = [
        dict(row)
        for row in connection.execute(
            f"""
            SELECT category,
                   COUNT(*)                  AS transaction_count,
                   SUM(amount_cents)         AS total_cents,
                   SUM(amount_cents) / 100.0 AS total_kes,
                   ROUND(100.0 * SUM(amount_cents)
                         / SUM(SUM(amount_cents)) OVER (), 2) AS share_pct
            FROM v_transactions
            WHERE {where}
            GROUP BY category
            ORDER BY total_cents DESC, category
            """,
            params,
        )
    ]
    merchants = [
        dict(row)
        for row in connection.execute(
            f"""
            SELECT merchant,
                   COUNT(*)                  AS transaction_count,
                   SUM(amount_cents) / 100.0 AS total_kes
            FROM v_transactions
            WHERE {where}
            GROUP BY merchant
            ORDER BY SUM(amount_cents) DESC, merchant
            LIMIT ?
            """,
            [*params, MERCHANT_LIMIT],
        )
    ]
    payments = [
        dict(row)
        for row in connection.execute(
            f"""
            SELECT payment_method,
                   COUNT(*)                  AS transaction_count,
                   SUM(amount_cents) / 100.0 AS total_kes
            FROM v_transactions
            WHERE {where}
            GROUP BY payment_method
            ORDER BY SUM(amount_cents) DESC, payment_method
            """,
            params,
        )
    ]

    total = int(kpis["transaction_count"])
    page_count = max(1, (total + filters.per_page - 1) // filters.per_page)
    page = min(max(filters.page, 1), page_count)
    offset = (page - 1) * filters.per_page
    transactions = [
        dict(row)
        for row in connection.execute(
            f"""
            SELECT transaction_id,
                   transaction_date,
                   profile_label,
                   student_id,
                   category,
                   merchant,
                   description,
                   payment_method,
                   amount_kes,
                   is_anomaly,
                   anomaly_reason
            FROM v_transactions
            WHERE {where}
            ORDER BY {SORT_CHOICES[filters.sort][1]}
            LIMIT ? OFFSET ?
            """,
            [*params, filters.per_page, offset],
        )
    ]
    first_row = offset + 1 if total else 0
    last_row = offset + len(transactions)

    return DashboardData(
        kpis=kpis,
        months=months,
        categories=categories,
        merchants=merchants,
        payments=payments,
        transactions=transactions,
        page=page,
        page_count=page_count,
        first_row=first_row,
        last_row=last_row,
    )


def load_run(connection: sqlite3.Connection) -> dict:
    row = connection.execute(
        "SELECT run_id, status, finished_at FROM pipeline_runs "
        "ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row is not None else {}


def _href(filters: Filters, *, page: int | None = None) -> str:
    query = urllib.parse.urlencode(filters.to_query(page=page))
    return escape_attr(f"/?{query}" if query else "/")


def _export_href(filters: Filters) -> str:
    query = filters.to_query()
    query.pop("page", None)
    query.pop("per_page", None)
    return escape_attr(f"/export.csv?{urllib.parse.urlencode(query)}")


def _dataset_href(filters: Filters, path: str = "/") -> str:
    if not filters.analysis:
        return escape_attr(path)
    query = urllib.parse.urlencode({"analysis": filters.analysis})
    return escape_attr(f"{path}?{query}")


def _analysis_suffix(analysis: AnalysisWorkspace | None) -> str:
    if analysis is None:
        return ""
    return "?" + urllib.parse.urlencode({"analysis": analysis.analysis_id})


def _kpi_cards(kpis: dict) -> str:
    flagged = int(kpis["flagged_count"])
    cards = [
        ("Total spend", f"KES {money(kpis['total_kes'])}", "matching the current filters"),
        ("Transactions", integer(kpis["transaction_count"]),
         f"{integer(flagged)} flagged for review" if flagged else "none flagged for review"),
        ("Students", integer(kpis["student_count"]), "distinct student profiles"),
        ("Average transaction", f"KES {money(kpis['avg_transaction_kes'])}",
         f"KES {money(kpis['avg_daily_kes'])} per day across "
         f"{integer(kpis['days_covered'])} days"),
    ]
    cells = "".join(
        f'<div class="card"><div class="label">{escape_attr(label)}</div>'
        f'<div class="value">{escape_attr(value)}</div>'
        f'<div class="hint">{escape_attr(hint)}</div></div>'
        for label, value, hint in cards
    )
    return f'<div class="cards dash-cards">{cells}</div>'


def _select_field(
    name: str,
    label: str,
    current: str,
    choices: list[tuple[str, str]],
) -> str:
    options = "".join(
        f'<option value="{escape_attr(value)}"'
        f'{" selected" if value == current else ""}>{escape_attr(text)}</option>'
        for value, text in choices
    )
    return (
        f'<div class="field"><label for="{escape_attr(name)}">{escape_attr(label)}</label>'
        f'<select id="{escape_attr(name)}" name="{escape_attr(name)}">{options}</select></div>'
    )


def _filter_panel(
    filters: Filters,
    options: FilterOptions,
    errors: list[str],
) -> str:
    error_html = ""
    if errors:
        items = " ".join(f"<span>{escape_attr(error)}</span>" for error in errors)
        error_html = f'<div class="banner bad" role="alert"><strong>Check the filters.</strong>{items}</div>'

    student_choices = [("", "All students")] + [
        (str(student["student_id"]), f"{student['profile_label']} ({student['student_id']})")
        for student in options.students
    ]
    category_choices = [("", "All categories")] + [
        (category, category) for category in options.categories
    ]
    payment_choices = [("", "All payment methods")] + [
        (payment, payment) for payment in options.payments
    ]
    flag_choices = list(FLAG_CHOICES.items())
    sort_choices = [(key, value[0]) for key, value in SORT_CHOICES.items()]
    per_page_choices = [(str(size), f"{size} per page") for size in PER_PAGE_CHOICES]

    date_limits = ""
    if options.first_date and options.last_date:
        date_limits = (
            f' min="{escape_attr(options.first_date)}" max="{escape_attr(options.last_date)}"'
        )

    return f"""
  <section class="panel" id="filters" aria-labelledby="filters-title">
    <p class="eyebrow">Filters</p>
    <h2 id="filters-title">Choose what you want to see</h2>
    <p class="lead">Every number below follows these controls. Filters combine, so you
      can narrow to one student, one category and a date window at the same time.</p>
    {error_html}
    <form class="filters" method="get" action="/#summary" aria-labelledby="filters-title">
      {'<input type="hidden" name="analysis" value="' + escape_attr(filters.analysis) + '">' if filters.analysis else ''}
      <div class="field">
        <label for="from">Start date</label>
        <input id="from" name="from" type="date" value="{escape_attr(filters.date_from)}"{date_limits} required>
      </div>
      <div class="field">
        <label for="to">End date</label>
        <input id="to" name="to" type="date" value="{escape_attr(filters.date_to)}"{date_limits} required>
      </div>
      {_select_field("student", "Student", filters.student_id, student_choices)}
      {_select_field("category", "Category", filters.category, category_choices)}
      {_select_field("payment", "Payment method", filters.payment_method, payment_choices)}
      {_select_field("flag", "Review status", filters.flag, flag_choices)}
      {_select_field("sort", "Sort transactions", filters.sort, sort_choices)}
      {_select_field("per_page", "Rows per page", str(filters.per_page), per_page_choices)}
      <div class="field field-search">
        <label for="q">Search merchant or description</label>
        <input id="q" name="q" type="search" maxlength="{SEARCH_LIMIT}"
          value="{escape_attr(filters.search)}" placeholder="e.g. cafeteria"
          autocomplete="off" spellcheck="false">
      </div>
      <div class="actions">
        <button class="button primary" type="submit">Apply filters</button>
        <a class="button ghost" href="{_dataset_href(filters)}">Reset everything</a>
      </div>
      <p class="note">The dashboard reads this warehouse in read-only mode. Filter values
        are not stored; uploaded datasets stay on this server.</p>
    </form>
  </section>"""


def _active_filter_list(filters: Filters, options: FilterOptions) -> str:
    items: list[str] = []
    if filters.student_id:
        label = next(
            (
                student["profile_label"]
                for student in options.students
                if str(student["student_id"]) == filters.student_id
            ),
            filters.student_id,
        )
        items.append(f"Student: {label}")
    if filters.category:
        items.append(f"Category: {filters.category}")
    if filters.payment_method:
        items.append(f"Payment: {filters.payment_method}")
    if filters.search:
        items.append(f"Search: “{filters.search}”")
    if filters.anomalies_only:
        items.append("Flagged only")
    if filters.sort != "newest":
        items.append(f"Sort: {SORT_CHOICES[filters.sort][0]}")
    if filters.per_page != 25:
        items.append(f"{filters.per_page} rows per page")
    if not items:
        return ""
    chips = "".join(f"<li>{escape_attr(item)}</li>" for item in items)
    return (
        f'<ul class="active-filters" aria-label="Active filters">{chips}'
        f'<li><a class="clear" href="{_dataset_href(filters)}">Clear all</a></li></ul>'
    )


def _plural(count: object, singular: str, plural: str | None = None) -> str:
    return (
        f"{integer(count)} "
        f"{singular if int(count) == 1 else (plural or singular + 's')}"
    )


def _summary_sentence(kpis: dict) -> str:
    total = int(kpis["transaction_count"])
    if total == 0:
        return "No clean transactions match these filters."
    flagged = int(kpis["flagged_count"])
    if flagged:
        flag_text = (
            f"{_plural(flagged, 'transaction')} "
            f"{'is' if flagged == 1 else 'are'} flagged for review."
        )
    else:
        flag_text = "No transactions are flagged for review."
    days = int(kpis["days_covered"])
    verb = "totals" if total == 1 else "total"
    return (
        f"{_plural(total, 'transaction')} from "
        f"{_plural(kpis['student_count'], 'student')} {verb} "
        f"KES {money(kpis['total_kes'])}. The average transaction is "
        f"KES {money(kpis['avg_transaction_kes'])}, and the slice covers "
        f"{_plural(days, 'day')} at KES {money(kpis['avg_daily_kes'])} "
        f"per day. {flag_text}"
    )


def _summary_panel(
    filters: Filters,
    options: FilterOptions,
    data: DashboardData,
) -> str:
    kpis = data.kpis
    total = int(kpis["transaction_count"])
    active = _active_filter_list(filters, options)
    range_text = f"{filters.date_from} to {filters.date_to}"
    if total == 0:
        return f"""
  <section class="panel" id="summary" aria-labelledby="summary-title">
    <p class="eyebrow"><span class="section-no">01</span> Results</p>
    <h2 id="summary-title">Nothing matches yet</h2>
    <p class="lead">{escape_attr(_summary_sentence(kpis))}</p>
    <p class="empty"><strong>Try a wider view.</strong> Extend the date range, choose all
      categories, or clear the search text. The warehouse stays unchanged.</p>
    <p><a class="button primary" href="{_dataset_href(filters)}">Reset the filters</a></p>
    {active}
  </section>"""

    flag_link = ""
    if int(kpis["flagged_count"]) and not filters.anomalies_only:
        flag_query = replace(filters, flag="anomalies", page=1)
        flag_link = (
            '<p class="flag-note">'
            f'<a class="button ghost small" href="{_href(flag_query)}">'
            f'Show only the {integer(kpis["flagged_count"])} flagged</a></p>'
        )
    return f"""
  <section class="panel" id="summary" aria-labelledby="summary-title">
    <p class="eyebrow"><span class="section-no">01</span> Results</p>
    <h2 id="summary-title">What matches</h2>
    <p class="lead">{escape_attr(_summary_sentence(kpis))}</p>
    {_kpi_cards(kpis)}
    <div class="resultbar">
      <p><strong>{escape_attr(range_text)}</strong> · showing
        {integer(data.first_row)}–{integer(data.last_row)} of
        {integer(total)} matching transactions</p>
      <a class="button primary small" href="{_export_href(filters)}" download>
        Download these rows as CSV</a>
    </div>
    {flag_link}
    {active}
  </section>"""


def _pagination(filters: Filters, data: DashboardData) -> str:
    if data.page_count <= 1:
        return ""
    previous = (
        f'<a class="button ghost small" href="{_href(filters, page=data.page - 1)}" '
        'rel="prev">&larr; Previous</a>'
        if data.page > 1
        else '<span class="button ghost small disabled" aria-disabled="true">&larr; Previous</span>'
    )
    following = (
        f'<a class="button ghost small" href="{_href(filters, page=data.page + 1)}" '
        'rel="next">Next &rarr;</a>'
        if data.page < data.page_count
        else '<span class="button ghost small disabled" aria-disabled="true">Next &rarr;</span>'
    )
    return (
        f'<nav class="pager" aria-label="Transaction pages">{previous}'
        f'<span class="page-label">Page {integer(data.page)} of '
        f'{integer(data.page_count)}</span>{following}</nav>'
    )


def _transaction_rows(rows: list[dict]) -> tuple[list[list[str]], list[str]]:
    body: list[list[str]] = []
    classes: list[str] = []
    for row in rows:
        flagged = bool(row["is_anomaly"])
        if flagged:
            reason = escape_attr(row["anomaly_reason"] or "Flagged for review")
            review = f'<span class="pill pill-review" title="{reason}">FLAGGED</span>'
        else:
            review = '<span class="muted">&mdash;</span>'
        body.append(
            [
                escape_attr(row["transaction_date"]),
                escape_attr(row["profile_label"]),
                escape_attr(row["category"]),
                '<span class="cell-merchant">'
                f'<strong>{escape_attr(row["merchant"])}</strong>'
                f'<span class="sub">{escape_attr(row["description"])}</span></span>',
                escape_attr(row["payment_method"]),
                money(row["amount_kes"]),
                review,
            ]
        )
        classes.append("alert" if flagged else "")
    return body, classes


def _transactions_panel(filters: Filters, data: DashboardData) -> str:
    body, classes = _transaction_rows(data.transactions)
    rows = table(
        [("Date", False), ("Student", False), ("Category", False),
         ("Merchant and description", False), ("Payment", False),
         ("Amount KES", True), ("Review", False)],
        body,
        row_classes=classes,
        empty_message="No transactions match these filters.",
    )
    return f"""
  <section class="panel" id="transactions" aria-labelledby="transactions-title">
    <p class="eyebrow"><span class="section-no">02</span> Transactions</p>
    <h2 id="transactions-title">Every matching row</h2>
    <p class="lead">Clean, accepted transactions only. Flagged rows are valid; they are
      unusually large for that student and category, so they stay in the table.</p>
    <div class="table-meta">
      <span>Showing {integer(data.first_row)}–{integer(data.last_row)} of
        {integer(data.kpis['transaction_count'])} rows</span>
      <span>Page {integer(data.page)} of {integer(data.page_count)}</span>
    </div>
    {rows}
    {_pagination(filters, data)}
  </section>"""


def _trend_panel(data: DashboardData) -> str:
    if not data.months:
        return ""
    chart = bar_chart(
        data.months,
        "transaction_month",
        "total_kes",
        title="Monthly spending for the current filters",
        gradient_id="dashboard-monthly",
    )
    rows = [
        [escape_attr(month["transaction_month"]), integer(month["active_students"]),
         integer(month["transaction_count"]), money(month["total_kes"])]
        for month in data.months
    ]
    return f"""
  <section class="panel" id="trend" aria-labelledby="trend-title">
    <p class="eyebrow"><span class="section-no">03</span> Trend</p>
    <h2 id="trend-title">How the filtered spend moved</h2>
    <p class="lead">One bar per month that has rows inside your current filters. The
      table repeats the exact SQL totals.</p>
    {chart}
    {table([("Month", False), ("Students", True), ("Transactions", True),
            ("Total KES", True)], rows)}
  </section>"""


def _breakdown_panel(data: DashboardData) -> str:
    if not data.categories:
        return ""
    category_shares = display_share_pcts(
        [category["total_cents"] for category in data.categories]
    )
    category_rows = [
        [escape_attr(category["category"]), integer(category["transaction_count"]),
         money(category["total_kes"]), share_cell(share)]
        for category, share in zip(data.categories, category_shares)
    ]
    merchant_rows = [
        [escape_attr(merchant["merchant"]), integer(merchant["transaction_count"]),
         money(merchant["total_kes"])]
        for merchant in data.merchants
    ]
    payment_rows = [
        [escape_attr(payment["payment_method"]), integer(payment["transaction_count"]),
         money(payment["total_kes"])]
        for payment in data.payments
    ]
    return f"""
  <section class="panel" id="breakdown" aria-labelledby="breakdown-title">
    <p class="eyebrow"><span class="section-no">04</span> Breakdown</p>
    <h2 id="breakdown-title">Where the filtered money went</h2>
    <p class="lead">Category shares are percentages of the filtered total and use
      largest-remainder rounding, so they add up to exactly 100.0% for the rows you are
      looking at.</p>
    {table([("Category", False), ("Transactions", True), ("Total KES", True),
            ("Share", True)], category_rows)}
    <div class="split">
      <div>
        <h3>Top merchants</h3>
        <p class="section-note">The {len(merchant_rows)} largest merchants in this slice.</p>
        {table([("Merchant", False), ("Transactions", True), ("Total KES", True)],
               merchant_rows)}
      </div>
      <div>
        <h3>Payment methods</h3>
        <p class="section-note">How these transactions were paid.</p>
        {table([("Method", False), ("Transactions", True), ("Total KES", True)],
               payment_rows)}
      </div>
    </div>
  </section>"""


def _nav(has_results: bool) -> str:
    links = [("filters", "Filters"), ("summary", "Summary")]
    if has_results:
        links.extend(
            [
                ("transactions", "Transactions"),
                ("trend", "Trend"),
                ("breakdown", "Breakdown"),
            ]
        )
    anchors = "".join(
        f'<a href="#{anchor}">{escape_attr(label)}</a>' for anchor, label in links
    )
    return f'<nav class="toc" aria-label="Dashboard sections">{anchors}</nav>'


def _hero(
    run: dict,
    options: FilterOptions,
    transactions: int,
    report_available: bool,
    analysis: AnalysisWorkspace | None,
) -> str:
    status = str(run.get("status", "unknown"))
    dot_class = "status-dot" if status == "success" else "status-dot bad"
    report_link = (
        f'<a class="button ghost" href="/report{_analysis_suffix(analysis)}">'
        "Open the full report</a>"
        if report_available
        else ""
    )
    analysis_chip = (
        f'<li><span class="chip-key">Analysis</span>{escape_attr(analysis.title)}</li>'
        if analysis
        else ""
    )
    scope = "this analysis" if analysis else "the warehouse"
    return f"""
  <header class="hero dash-hero" id="top">
    <p class="eyebrow">Synthetic data &middot; analysis workspace</p>
    <h1>Spending <span>Explorer</span></h1>
    <p class="lede">Filter every clean transaction in {scope} and see the summary,
      monthly trend and breakdown update together. Every figure is a SQL result.</p>
    <div class="hero-actions">
      <a class="button primary" href="/plan">Plan my money</a>
      <a class="button ghost" href="#filters">Start filtering</a>
      {report_link}
      <a class="button ghost" href="/upload">Analyze new data</a>
    </div>
    <ul class="chips">
      {analysis_chip}
      <li><span class="chip-key">Data through</span>{escape_attr(options.last_date or "n/a")}</li>
      <li><span class="chip-key">Warehouse</span>{integer(transactions)} clean
        {("row" if int(transactions) == 1 else "rows")}</li>
      <li><span class="chip-key">Run</span><code>{escape_attr(run.get("run_id", "not run yet"))}</code></li>
      <li><span class="chip-key">Status</span><span class="{dot_class}"></span>
        {escape_attr(status)}</li>
    </ul>
    <p class="disclaimer"><strong>Synthetic data.</strong> Every record was generated for
      a learning exercise. Nothing describes real students, accounts, cards or payments.</p>
  </header>"""


def _analysis_notice(analysis: AnalysisWorkspace | None, report_available: bool) -> str:
    if analysis is None or not analysis.quality_failures:
        return ""
    report_link = (
        f' <a href="/report{_analysis_suffix(analysis)}">Open the full report</a>.'
        if report_available
        else "."
    )
    checks = _plural(analysis.quality_failures, "automated quality check")
    return (
        '<div class="banner bad" role="status"><strong>Quality alert.</strong> '
        f"{checks} failed while building this analysis. The rows are still visible;"
        f" review the evidence before relying on the totals{report_link}</div>"
    )


def _footer(
    run: dict,
    report_available: bool,
    analysis: AnalysisWorkspace | None,
) -> str:
    report_note = (
        f'<a class="totop" href="/report{_analysis_suffix(analysis)}">'
        "Open the full static report</a>"
        if report_available
        else '<span class="section-note">Run <code>student-spending</code> to generate '
             "the full static report.</span>"
    )
    dataset_note = (
        f"This dashboard is showing the uploaded analysis "
        f"<strong>{escape_attr(analysis.title)}</strong> "
        f"(<code>{escape_attr(analysis.analysis_id)}</code>)."
        if analysis
        else "This dashboard is showing the committed synthetic warehouse."
    )
    return f"""
  <footer class="panel footer">
    <p><strong>Read-only by design.</strong> Filters are validated, every value reaches
      SQLite as a bound parameter, and the warehouse is opened with <code>mode=ro</code>.
      Filter values are not written or stored.</p>
    <p class="section-note">{dataset_note}</p>
    <p class="section-note">{escape_attr(legal.DISCLAIMER)}</p>
    <p class="meta-line">Student Spending Analytics &middot; latest run
      <code>{escape_attr(run.get("run_id", "none"))}</code> &middot; finished
      <code>{escape_attr(run.get("finished_at") or "not finished")}</code></p>
    <div class="footer-links">{_legal_links()}{report_note}
      <a class="totop" href="/plan">Plan your own money</a>
      <a class="totop" href="/upload">Analyze another dataset</a>
      <a class="totop" href="#top">Back to top</a></div>
  </footer>"""


def render_dashboard(
    connection: sqlite3.Connection,
    query: dict[str, list[str]],
    *,
    report_available: bool,
    analysis: AnalysisWorkspace | None = None,
    account: Account | None = None,
) -> str:
    options = load_options(connection)
    filters, errors = parse_filters(query, options)
    if analysis is not None:
        filters = replace(filters, analysis=analysis.analysis_id)
    data = load_dashboard(connection, filters)
    run = load_run(connection)
    total_warehouse = connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    has_results = int(data.kpis["transaction_count"]) > 0
    body = f"""
<main class="shell">
  {_account_bar(account)}
  {_hero(run, options, int(total_warehouse), report_available, analysis)}
  {_analysis_notice(analysis, report_available)}
  {_nav(has_results)}
  {_filter_panel(filters, options, errors)}
  {_summary_panel(filters, options, data)}
  {_transactions_panel(filters, data) if has_results else ""}
  {_trend_panel(data) if has_results else ""}
  {_breakdown_panel(data) if has_results else ""}
  {_footer(run, report_available, analysis)}
</main>
"""
    page_title = (
        f"{analysis.title} · Spending Explorer" if analysis else "Spending Explorer"
    )
    return _document(f"{page_title} · Student Spending Analytics", body)


def _csv_safe(value: object) -> str:
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def render_csv(connection: sqlite3.Connection, filters: Filters) -> str:
    where, params = build_where(filters)
    rows = connection.execute(
        f"""
        SELECT transaction_id, transaction_date, student_id, profile_label,
               category, merchant, description, payment_method, amount_kes,
               is_anomaly, anomaly_reason
        FROM v_transactions
        WHERE {where}
        ORDER BY {SORT_CHOICES[filters.sort][1]}
        """,
        params,
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["transaction_id", "transaction_date", "student_id", "profile_label",
         "category", "merchant", "description", "payment_method", "amount_kes",
         "is_anomaly", "anomaly_reason"]
    )
    for row in rows:
        writer.writerow(
            [
                _csv_safe(row["transaction_id"]),
                _csv_safe(row["transaction_date"]),
                _csv_safe(row["student_id"]),
                _csv_safe(row["profile_label"]),
                _csv_safe(row["category"]),
                _csv_safe(row["merchant"]),
                _csv_safe(row["description"]),
                _csv_safe(row["payment_method"]),
                f"{float(row['amount_kes']):.2f}",
                "yes" if row["is_anomaly"] else "no",
                _csv_safe(row["anomaly_reason"]),
            ]
        )
    return buffer.getvalue()


def render_plan_csv(plan: MoneyPlan, analysis: PlanAnalysis) -> str:
    """The same plan figures as the page, in a spreadsheet-friendly file."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Plan It money plan export"])
    writer.writerow(["Recorded", _csv_safe(analysis.recorded_at.isoformat(timespec="minutes"))])
    writer.writerow(["Student", _csv_safe(plan.student_name)])
    writer.writerow(["Period", _csv_safe(plan.period_label)])
    writer.writerow(["Method", _csv_safe(BUDGET_METHODS[plan.method])])
    writer.writerow(["Money available (KES)", f"{analysis.money_available_cents / 100:.2f}"])
    writer.writerow([])
    writer.writerow(["Categories"])
    writer.writerow(
        ["Category", "Type", "Planned KES", "Spent KES", "Planned minus spent KES",
         "Share of spending %", "Status"]
    )
    shares = display_share_pcts([item.share_pct for item in analysis.categories])
    for item, share in zip(analysis.categories, shares):
        writer.writerow(
            [
                _csv_safe(item.name),
                "Essential" if item.essential else "Flexible",
                f"{item.planned_cents / 100:.2f}",
                f"{item.spent_cents / 100:.2f}",
                f"{item.difference_cents / 100:.2f}",
                f"{share:.1f}",
                _csv_safe(item.status),
            ]
        )
    writer.writerow(
        [
            "Total",
            "",
            f"{analysis.planned_cents / 100:.2f}",
            f"{analysis.spent_cents / 100:.2f}",
            f"{(analysis.planned_cents - analysis.spent_cents) / 100:.2f}",
            "100.0",
            "",
        ]
    )
    writer.writerow([])
    writer.writerow(["Spending entries"])
    writer.writerow(["Category", "Note", "Amount KES"])
    for entry in plan.spendings:
        writer.writerow(
            [
                _csv_safe(entry.category),
                _csv_safe(entry.note),
                f"{entry.amount_cents / 100:.2f}",
            ]
        )
    writer.writerow([])
    writer.writerow(["Summary"])
    writer.writerow(["Planned total KES", f"{analysis.planned_cents / 100:.2f}"])
    writer.writerow(["Recorded spending KES", f"{analysis.spent_cents / 100:.2f}"])
    writer.writerow(["Left unspent KES", f"{analysis.remaining_cents / 100:.2f}"])
    writer.writerow(["Unallocated KES", f"{analysis.unallocated_cents / 100:.2f}"])
    writer.writerow(["Average per entry KES", f"{analysis.average_entry_cents / 100:.2f}"])
    writer.writerow([])
    writer.writerow([legal.DISCLAIMER])
    return buffer.getvalue()


def _upload_errors(errors: list[str]) -> str:
    if not errors:
        return ""
    items = " ".join(f"<span>{escape_attr(error)}</span>" for error in errors)
    return f'<div class="banner bad" role="alert"><strong>Check the upload.</strong>{items}</div>'


def _file_field(field: str, *, full: bool = False) -> str:
    label, columns, _ = FILE_FIELDS[field]
    required = ", ".join(columns)
    return f"""
      <div class="field{' field-full' if full else ''}">
        <label for="{escape_attr(field)}">{escape_attr(label)} <span class="section-note">required</span></label>
        <input id="{escape_attr(field)}" name="{escape_attr(field)}" type="file"
          accept=".csv,text/csv" required>
        <p class="columns">Required columns: {escape_attr(required)}</p>
      </div>"""


def _format_created(created_at: str) -> str:
    text = created_at.strip()
    if len(text) >= 16 and text[10] == "T":
        return text[:16].replace("T", " ") + " UTC"
    return text or "unknown time"


def _recent_analyses(analyses: list[AnalysisWorkspace]) -> str:
    if not analyses:
        return (
            '<p class="recent-empty">No uploaded analyses yet. The committed sample '
            "warehouse is still available from the dashboard.</p>"
        )
    items = []
    for analysis in analyses:
        if analysis.status == "quality_failed":
            status = '<span class="pill fail">quality alert</span>'
        else:
            status = '<span class="pill pass">success</span>'
        report_link = (
            f'<a class="button ghost small" href="/report{_analysis_suffix(analysis)}">'
            "Report</a>"
            if analysis.report_path.is_file()
            else ""
        )
        source = analysis.inputs.get("transactions", {})
        source_name = source.get("filename") if isinstance(source, dict) else ""
        source_rows = source.get("rows") if isinstance(source, dict) else ""
        source_note = ""
        if source_name:
            source_note = (
                f'<span class="section-note">{escape_attr(source_name)}'
                f' · {integer(source_rows)} rows</span>'
            )
        items.append(
            f"""
      <li>
        <div class="recent-main"><strong>{escape_attr(analysis.title)}</strong>{status}</div>
        <p class="recent-meta"><code>{escape_attr(analysis.analysis_id)}</code>
          · {escape_attr(_format_created(analysis.created_at))}
          · {integer(analysis.rows_accepted)} accepted rows</p>
        <div class="recent-actions">
          <a class="button primary small" href="/{_analysis_suffix(analysis)}">Open analysis</a>
          {report_link}<a class="button ghost small"
            href="/delete-analysis?{urllib.parse.urlencode({'analysis': analysis.analysis_id})}">Delete</a>{source_note}
        </div>
      </li>"""
        )
    return f'<ul class="recent-list">{"".join(items)}</ul>'


def render_upload_page(
    *,
    analyses: list[AnalysisWorkspace],
    errors: list[str] | None = None,
    title: str = "",
    current_analysis: AnalysisWorkspace | None = None,
    account: Account | None = None,
    notice: str = "",
) -> str:
    back_link = (
        f'<a class="button ghost" href="/{_analysis_suffix(current_analysis)}">'
        "Open current analysis</a>"
        if current_analysis
        else '<a class="button ghost" href="/">Open the sample dashboard</a>'
    )
    notice_html = (
        f'<p class="banner good" role="status">{escape_attr(notice)}</p>'
        if notice
        else ""
    )
    file_bytes = MAX_FILE_BYTES // (1024 * 1024)
    body = f"""
<main class="shell">
  {_account_bar(account)}
  <header class="hero dash-hero" id="top">
    <p class="eyebrow">Your data &middot; build an analysis</p>
    <h1>Analyze <span>your data</span></h1>
    <p class="lede">Upload one transactions CSV and the pipeline validates every row,
      derives the student list, loads an isolated warehouse and opens the same
      filterable dashboard. The file is processed on this server and scoped to your
      account.</p>
    <div class="hero-actions">
      <a class="button primary" href="#upload-form">Upload a CSV</a>
      <a class="button ghost" href="/plan">Plan my own money</a>
      {back_link}
    </div>
    <p class="disclaimer"><strong>Only data you may process.</strong> Upload records you
      have the right to use. Never upload card numbers, bank or mobile-money PINs,
      national ID numbers or another person's data.</p>
  </header>

  {notice_html}
  <nav class="toc" aria-label="Analysis workspace sections">
    <a href="#upload-form">Upload</a><a href="#recent">Recent analyses</a>
  </nav>

  <div class="upload-grid">
    <section class="panel" id="upload-form" aria-labelledby="upload-title">
      <p class="eyebrow">New analysis</p>
      <h2 id="upload-title">One CSV, one analysed warehouse</h2>
      <p class="lead">The transactions file is the only input. Student labels come from
        <code>student_id</code>, so there is no separate profile file, and budget
        variance is skipped. Download the sample below for a known-good starting point.</p>
      {_upload_errors(errors or [])}
      <form class="upload-form" method="post" action="/upload" enctype="multipart/form-data">
        {csrf_field()}
        <div class="field field-full">
          <label for="analysis-title">Analysis name <span class="section-note">optional</span></label>
          <input id="analysis-title" name="title" type="text" maxlength="{MAX_TITLE_LENGTH}"
            value="{escape_attr(title)}" placeholder="e.g. October spending"
            autocomplete="off">
        </div>
        {_file_field("transactions", full=True)}
        <div class="field-full sample-links">
          <span>Sample input:</span>
          <a href="/samples/student_expenses.csv" download>transactions</a>
        </div>
        <label class="check-field">
          <input type="checkbox" name="authorised" value="yes" required>
          <span><strong>I have the right to process this file.</strong> It contains no
            card numbers, bank or mobile-money PINs, national ID numbers or another
            person's data.</span>
        </label>
        <div class="actions">
          <button class="button primary" type="submit">Run analysis</button>
          <span class="section-note">The pipeline runs immediately; this may take a moment.</span>
        </div>
        <p class="upload-note">Limits: one .csv file, {file_bytes} MB and
          {MAX_CSV_ROWS:,} data rows. The file is stored in the operator's upload
          directory; each analysis gets its own database and report. Do not upload
          payment credentials. No profiles or budgets file is required.</p>
      </form>
    </section>

    <aside class="panel" id="recent" aria-labelledby="recent-title">
      <p class="eyebrow">History</p>
      <h2 id="recent-title">Recent analyses</h2>
      <p class="lead">Only analyses that completed loading appear here. Each one keeps
        its inputs, SQLite warehouse and report on this server.</p>
      {_recent_analyses(analyses)}
      <ol class="upload-steps">
        <li><strong>Check</strong> the headers, encoding, row count and size.</li>
        <li><strong>Build</strong> the warehouse with the normal pipeline.</li>
        <li><strong>Explore</strong> the dashboard, CSV export and quality report.</li>
      </ol>
    </aside>
  </div>

  <footer class="panel footer">
    <p><strong>Read-only after loading.</strong> The upload and money-plan endpoints
      are the only analysis write paths, and analysis pages open SQLite with
      <code>mode=ro</code>. Upload only records you have the right to process, and
      never enter payment credentials.</p>
    <p class="meta-line">Plan It &middot; personal spending analysis</p>
    <p class="section-note">{escape_attr(legal.DISCLAIMER)}</p>
    <div class="footer-links">
      {_legal_links()}
      <a class="totop" href="/">Open the sample dashboard</a>
      <a class="totop" href="/plan">Plan your own money</a>
      <a class="totop" href="#top">Back to top</a>
    </div>
  </footer>
</main>
"""
    return _document("Analyze data · Student Spending Analytics", body, skip_href=None)


def _plan_error_banner(errors: list[str]) -> str:
    if not errors:
        return ""
    items = "".join(f"<li>{escape_attr(error)}</li>" for error in errors)
    return (
        '<div class="banner bad" role="alert"><strong>Check these details.</strong>'
        f'<ul class="error-list">{items}</ul></div>'
    )


def _category_row(number: int, row: object, *, is_new: bool = False) -> str:
    essential = bool(getattr(row, "essential", False))
    autofocus = " autofocus" if is_new else ""
    return f"""
      <div class="plan-row cat-cols{" plan-row-new" if is_new else ""}"
        id="plan-cat-{number}">
        <span class="row-no" aria-hidden="true">{number:02d}</span>
        <input name="category_name_{number}" type="text" maxlength="{MAX_CATEGORY_NAME_LENGTH}"
          value="{escape_attr(getattr(row, 'name', ''))}" placeholder="e.g. Food"
          aria-label="Category {number} name" autocomplete="off"{autofocus}>
        <input name="category_amount_{number}" type="text" inputmode="decimal"
          value="{escape_attr(getattr(row, 'planned', ''))}" placeholder="0.00"
          aria-label="Category {number} planned amount in KES">
        <select name="category_essential_{number}" aria-label="Category {number} type">
          <option value="essential"{" selected" if essential else ""}>Essential</option>
          <option value="flexible"{" selected" if not essential else ""}>Flexible</option>
        </select>
      </div>"""


def _spending_row(number: int, row: object, *, is_new: bool = False) -> str:
    autofocus = " autofocus" if is_new else ""
    return f"""
      <div class="plan-row spend-cols{" plan-row-new" if is_new else ""}"
        id="plan-spend-{number}">
        <span class="row-no" aria-hidden="true">{number:02d}</span>
        <input name="spending_category_{number}" type="text"
          maxlength="{MAX_CATEGORY_NAME_LENGTH}"
          value="{escape_attr(getattr(row, 'category', ''))}" placeholder="Your category"
          aria-label="Spending row {number} category" autocomplete="off"{autofocus}>
        <input name="spending_amount_{number}" type="text" inputmode="decimal"
          value="{escape_attr(getattr(row, 'amount', ''))}" placeholder="0.00"
          aria-label="Spending row {number} amount in KES">
        <input name="spending_note_{number}" type="text"
          maxlength="{MAX_ENTRY_NOTE_LENGTH}"
          value="{escape_attr(getattr(row, 'note', ''))}" placeholder="Optional note"
          aria-label="Spending row {number} note" autocomplete="off">
      </div>"""


def _add_row_control(
    *,
    section: str,
    action: str,
    noun: str,
    rows: int,
    maximum: int,
    label: str,
) -> str:
    if rows >= maximum:
        return (
            f'<span class="section-note">{maximum} {noun} rows is the maximum.</span>'
        )
    return (
        '<div class="plan-add">'
        f'<span class="section-note">{rows} of {maximum} {noun} rows</span>'
        '<button class="button ghost plan-add-button" type="submit" '
        f'name="action" value="{action}" formaction="/plan#{section}-end" '
        f'formnovalidate aria-label="{label}" title="{label}">'
        '<span aria-hidden="true">+</span></button>'
        "</div>"
    )


def render_plan_page(
    *,
    draft: PlanDraft | None = None,
    errors: list[str] | None = None,
    plan: MoneyPlan | None = None,
    analysis: PlanAnalysis | None = None,
    category_rows: int = CATEGORY_ROWS,
    spending_rows: int = SPENDING_ROWS,
    new_category_row: int | None = None,
    new_spending_row: int | None = None,
    coach_question: str = "",
    coach_reply: CoachReply | None = None,
    account: Account | None = None,
) -> str:
    draft = draft or PlanDraft()
    errors = errors or []
    period_noun = PERIOD_NOUNS.get(draft.period, PERIOD_NOUNS["monthly"])
    category_rows = min(
        max(CATEGORY_ROWS, len(draft.categories), category_rows), MAX_CATEGORIES
    )
    spending_rows = min(
        max(SPENDING_ROWS, len(draft.spendings), spending_rows), MAX_SPENDINGS
    )
    categories_html = "".join(
        _category_row(number, draft.category(number), is_new=number == new_category_row)
        for number in range(1, category_rows + 1)
    )
    spendings_html = "".join(
        _spending_row(number, draft.spending(number), is_new=number == new_spending_row)
        for number in range(1, spending_rows + 1)
    )
    analysis_html = (
        _plan_analysis_sections(
            plan,
            analysis,
            draft,
            category_rows=category_rows,
            spending_rows=spending_rows,
            coach_question=coach_question,
            coach_reply=coach_reply,
        )
        if plan is not None and analysis is not None
        else ""
    )
    analysis_link = (
        '<a href="#analysis">Analysis</a><a href="#analysis-receipt">Receipt</a>'
        '<a href="#coach">Coach</a>'
        if analysis_html
        else ""
    )
    analysis_action = (
        '<a class="button ghost" href="#analysis">See the analysis</a>'
        if analysis_html
        else ""
    )
    add_category = _add_row_control(
        section="categories",
        action="add_category",
        noun="category",
        rows=category_rows,
        maximum=MAX_CATEGORIES,
        label="Add another category",
    )
    add_spending = _add_row_control(
        section="spending",
        action="add_spending",
        noun="spending",
        rows=spending_rows,
        maximum=MAX_SPENDINGS,
        label="Add another spending row",
    )
    body = f"""
<main class="shell">
  {_account_bar(account)}
  <header class="hero dash-hero" id="top">
    <p class="eyebrow">One student &middot; local money plan</p>
    <h1>Plan your <span>money</span></h1>
    <p class="lede">Enter the money you have, name your own categories, and record what
      you actually spent. The analysis compares your plan with your entries and charts
      where the money went.</p>
    <div class="hero-actions">
      <a class="button primary" href="#money">Start with the money</a>
      {analysis_action}
      <a class="button ghost" href="/">Explore the sample dataset</a>
    </div>
    <p class="disclaimer"><strong>A planning tool, not advice.</strong> Plan It compares
      the figures you enter; it does not provide financial advice. Never enter account
      numbers, card details, mobile-money PINs or payment credentials. Your plan is
      rendered on this server and is not saved.</p>
  </header>

  <nav class="toc" aria-label="Money plan sections">
    <a href="#money">Money</a><a href="#categories">Categories</a>
    <a href="#spending">Spending</a><a href="#review">Review</a>{analysis_link}
  </nav>

  <form class="plan-form" method="post" action="/plan#analysis" accept-charset="utf-8">
    {csrf_field()}
    <input type="hidden" name="category_rows" value="{category_rows}">
    <input type="hidden" name="spending_rows" value="{spending_rows}">
    <section class="panel" id="money" aria-labelledby="money-title">
      <p class="eyebrow"><span class="section-no">01</span> Money</p>
      <h2 id="money-title">What you have and how you plan</h2>
      <p class="lead">Start with a display name, choose whether you are planning a week
        or a month, and enter the money available for that period. The budgeting method
        is a label for your approach; the category amounts are what the comparison
        uses.</p>
      {_plan_error_banner(errors)}
      <div class="plan-grid">
        <div class="field">
          <label for="student_name">Display name</label>
          <input id="student_name" name="student_name" type="text"
            maxlength="{MAX_NAME_LENGTH}" value="{escape_attr(draft.student_name)}"
            placeholder="A nickname is fine" autocomplete="off">
        </div>
        <div class="field">
          <label for="money_available">Money available per {period_noun} (KES)</label>
          <input id="money_available" name="money_available" type="text"
            inputmode="decimal" value="{escape_attr(draft.money_available)}"
            placeholder="e.g. 18,000">
        </div>
        {_select_field("period", "Planning period", draft.period,
                       list(PERIODS.items()))}
        {_select_field("method", "Budgeting method", draft.method,
                       list(BUDGET_METHODS.items()))}
        <div class="field field-full">
          <label for="method_note">How you budget <span class="section-note">optional</span></label>
          <textarea id="method_note" name="method_note"
            maxlength="{MAX_METHOD_NOTE_LENGTH}"
            placeholder="e.g. I split my money into weekly envelopes and put rent aside first.">{escape_attr(draft.method_note)}</textarea>
        </div>
      </div>
      <p class="plan-section-note">Amounts are in KES. Commas and a decimal point are
        fine: 18,000 or 18,000.50. The period changes the wording and the coach&rsquo;s
        advice, not the numbers, so enter the money and the spending for the same
        period.</p>
    </section>

    <section class="panel" id="categories" aria-labelledby="categories-title">
      <p class="eyebrow"><span class="section-no">02</span> Categories</p>
      <h2 id="categories-title">Name your own categories</h2>
      <p class="lead">There is no fixed category list: use the names you think in.
        Add a planned amount if you have one, and mark each category Essential or
        Flexible. Use the + under the list to add a row. Blank rows are ignored;
        at least two categories are needed.</p>
      <div class="plan-rows">
        <div class="plan-row-head cat-cols">
          <span>#</span><span>Category name</span><span>Planned KES</span><span>Type</span>
        </div>
        {categories_html}
      </div>
      <div id="categories-end"></div>
      {add_category}
      <p class="plan-section-note">Leaving Planned KES blank means zero for that
        category. Spending in a category with a zero plan is still included, and the
        analysis marks it as having no plan.</p>
    </section>

    <section class="panel" id="spending" aria-labelledby="spending-title">
      <p class="eyebrow"><span class="section-no">03</span> Spending</p>
      <h2 id="spending-title">What you actually spent</h2>
      <p class="lead">One row per purchase or payment. Use a category name from above;
        matching ignores capitalisation. Use the + under the list to add a row. Leave
        any row blank if you do not need it. There is no date to type: every entry is
        stamped with this device's clock when you run the analysis.</p>
      <div class="plan-rows">
        <div class="plan-row-head spend-cols">
          <span>#</span><span>Category</span>
          <span>Amount KES</span><span>Note</span>
        </div>
        {spendings_html}
      </div>
      <div id="spending-end"></div>
      {add_spending}
      <p class="plan-section-note">At least one complete spending row is needed.
        The time comes from the device you are using and appears on the receipt.</p>
    </section>

    <section class="panel" id="review" aria-labelledby="review-title">
      <p class="eyebrow"><span class="section-no">04</span> Review</p>
      <h2 id="review-title">Run the analysis</h2>
      <p class="lead">The analysis adds up only the values in this form. It will show
        your totals, every category against its plan, and graphs of where the money
        went.</p>
      <label class="check-field">
        <input type="checkbox" name="advice_ack" value="yes"{" checked" if draft.advice_ack else ""} required>
        <span><strong>I understand Plan It is a planning tool.</strong> It does not
          provide financial, investment, tax or legal advice.</span>
      </label>
      <div class="plan-actions">
        <button class="button primary" type="submit">Run my analysis</button>
        <a class="button ghost" href="/plan">Clear the form</a>
        <span class="section-note">The analysis appears below this form.</span>
      </div>
      <p class="plan-section-note">The graphs and totals are generated in this page on
        this server. Nothing is saved as a separate plan link or file; your account
        only unlocks the form.</p>
    </section>
  </form>

  {analysis_html}

  <footer class="panel footer">
    <p><strong>Your figures, handled carefully.</strong> The form is validated on the
      server, amounts are stored as integer cents, and the analysis is rendered into
      this page. The password you signed in with is stored as a salted scrypt hash;
      no bank or card credentials are collected.</p>
    <p class="meta-line">Plan It &middot; money plan &middot; not financial advice</p>
    <p class="section-note">{escape_attr(legal.DISCLAIMER)}</p>
    <div class="footer-links">
      {_legal_links()}
      <a class="totop" href="/">Explore the sample dataset</a>
      <a class="totop" href="/upload">Analyze a transactions CSV</a>
      <a class="totop" href="#top">Back to top</a>
    </div>
  </footer>
</main>
"""
    return _document("Plan your money · Student Spending Analytics", body, skip_href=None)


def _plan_summary(plan: object, analysis: object) -> str:
    return (
        f"{plan.student_name} has KES {money(analysis.money_available_cents / 100)} "
        f"available for the {plan.period_noun}, planned "
        f"KES {money(analysis.planned_cents / 100)} across "
        f"{integer(len(plan.categories))} categories, and recorded "
        f"{integer(len(plan.spendings))} spending entries totalling "
        f"KES {money(analysis.spent_cents / 100)}."
    )


def _plan_cards(plan: object, analysis: object) -> str:
    if analysis.planned_cents:
        planned_hint = (
            f"{integer(len(plan.categories))} categories · "
            f"{percent(analysis.planned_share_pct)} of the money available"
        )
    else:
        planned_hint = f"{integer(len(plan.categories))} categories · no planned amounts"
    remaining = analysis.remaining_cents
    left_value = (
        f"KES {money(remaining / 100)}"
        if remaining >= 0
        else f"-KES {money(-remaining / 100)}"
    )
    cards = [
        ("Money available", f"KES {money(analysis.money_available_cents / 100)}",
         f"for the {plan.period_noun}"),
        ("Planned", f"KES {money(analysis.planned_cents / 100)}", planned_hint),
        ("Spent", f"KES {money(analysis.spent_cents / 100)}",
         f"{integer(len(plan.spendings))} entries · "
         f"{percent(analysis.spent_share_pct)} of the money available"),
        ("Left", left_value,
         "still unspent" if remaining >= 0 else "more than available"),
    ]
    cells = "".join(
        f'<div class="card"><div class="label">{escape_attr(label)}</div>'
        f'<div class="value">{escape_attr(value)}</div>'
        f'<div class="hint">{escape_attr(hint)}</div></div>'
        for label, value, hint in cards
    )
    return f'<div class="cards plan-cards">{cells}</div>'


def _plan_banners(plan: object, analysis: object) -> str:
    noun = plan.period_noun
    banners: list[tuple[str, str, str]] = []
    if analysis.remaining_cents > 0:
        banners.append(
            ("good", "Money available",
             f"KES {money(analysis.remaining_cents / 100)} of the money available for "
             f"the {noun} is still unspent.")
        )
    elif analysis.remaining_cents == 0:
        banners.append(
            ("good", "Money available",
             f"Recorded spending uses exactly the money available for the {noun}.")
        )
    else:
        banners.append(
            ("bad", "Money available",
             f"Recorded spending is KES {money(-analysis.remaining_cents / 100)} more "
             f"than the money available for the {noun}.")
        )
    if analysis.planned_cents == 0:
        banners.append(
            ("note", "Plan",
             "No planned amounts were entered, so this analysis compares actual spending only.")
        )
    elif analysis.unallocated_cents < 0:
        banners.append(
            ("bad", "Plan",
             f"The plan allocates KES {money(-analysis.unallocated_cents / 100)} more "
             f"than the money available for the {noun}.")
        )
    elif analysis.unallocated_cents == 0:
        banners.append(
            ("good", "Plan",
             f"The plan allocates exactly the money available for the {noun}.")
        )
    else:
        banners.append(
            ("note", "Plan",
             f"The plan leaves KES {money(analysis.unallocated_cents / 100)} unallocated; "
             "it can be a buffer.")
        )
    if analysis.near_plan:
        count = len(analysis.near_plan)
        verb = "category has" if count == 1 else "categories have"
        banners.append(
            ("note", "Close to plan",
             f"{count} {verb} used 80% or more of the planned amount but is not over it: "
             f"{_names(analysis.near_plan)}.")
        )
    return "".join(
        f'<div class="banner {kind}" role="status"><strong>{escape_attr(label)}.</strong> '
        f"{escape_attr(text)}</div>"
        for kind, label, text in banners
    )


def _names(items: list | tuple, limit: int = 4) -> str:
    names = [item.name for item in items]
    if len(names) > limit:
        return ", ".join(names[:limit]) + f" and {len(names) - limit} more"
    return ", ".join(names)


def _plan_insights(plan: object, analysis: object) -> str:
    items: list[str] = []
    biggest = analysis.ranked_categories[0]
    if biggest.spent_cents:
        items.append(
            f"{biggest.name} is the largest category: "
            f"KES {money(biggest.spent_cents / 100)} "
            f"({percent(biggest.share_pct)} of recorded spending)."
        )
    if analysis.over_plan:
        over_total = sum(
            item.spent_cents - item.planned_cents for item in analysis.over_plan
        )
        count = len(analysis.over_plan)
        verb = "category is" if count == 1 else "categories are"
        items.append(
            f"{count} {verb} over plan by "
            f"KES {money(over_total / 100)} in total: "
            f"{_names(analysis.over_plan)}."
        )
    elif analysis.planned_cents:
        items.append("Every category with a planned amount is at or under its plan.")
    if analysis.unplanned:
        unplanned_total = sum(item.spent_cents for item in analysis.unplanned)
        items.append(
            f"KES {money(unplanned_total / 100)} of spending has no planned amount: "
            f"{_names(analysis.unplanned)}."
        )
    if analysis.planned_cents:
        essential_plan_share = 100.0 * analysis.essential_planned_cents / analysis.planned_cents
        items.append(
            f"Essential categories are {percent(analysis.essential_share_pct)} of "
            f"spending (KES {money(analysis.essential_spent_cents / 100)}) and "
            f"{percent(essential_plan_share)} of the planned total "
            f"(KES {money(analysis.essential_planned_cents / 100)})."
        )
    else:
        items.append(
            f"Essential categories are {percent(analysis.essential_share_pct)} of "
            f"spending (KES {money(analysis.essential_spent_cents / 100)})."
        )
    items.append(
        f"You recorded {_plural(len(plan.spendings), 'spending row')}, averaging "
        f"KES {money(analysis.average_entry_cents / 100)} per row."
    )
    if analysis.planned_cents and analysis.unallocated_cents > 0:
        items.append(
            f"KES {money(analysis.unallocated_cents / 100)} of the money available is "
            "not assigned to a category plan yet."
        )
    list_html = "".join(f"<li>{escape_attr(item)}</li>" for item in items)
    return f'<ul class="insight-list">{list_html}</ul>'


def _plan_suggestions(plan: object, analysis: object) -> str:
    suggestions = coach_suggest(plan, analysis)
    cards = "".join(
        f'<li><div class="suggestion {escape_attr(item.tone)}">'
        f"<h4>{escape_attr(item.title)}</h4>"
        f"<p>{escape_attr(item.detail)}</p></div></li>"
        for item in suggestions
    )
    return (
        "<h3>How to spend it better</h3>"
        f'<ul class="suggestion-list">{cards}</ul>'
        '<p class="plan-section-note">Built from the figures above by fixed local '
        "rules. It is not financial advice and nothing leaves this server.</p>"
    )


def _plan_category_panel(plan: object, analysis: object) -> str:
    actual_items = [
        {"category": item.name, "spent_kes": item.spent_cents / 100}
        for item in analysis.ranked_categories
        if item.spent_cents
    ]
    compare_items = [
        {
            "category": item.name,
            "planned_kes": item.planned_cents / 100,
            "spent_kes": item.spent_cents / 100,
        }
        for item in analysis.ranked_categories
        if item.planned_cents or item.spent_cents
    ]
    actual_chart = bar_chart(
        actual_items,
        "category",
        "spent_kes",
        title="Spending by category",
        gradient_id="plan-actual",
    )
    compare_chart = grouped_bar_chart(
        compare_items,
        "category",
        [
            ("planned_kes", "Planned", "#c4b5fd", "#a78bfa"),
            ("spent_kes", "Spent", "#7c3aed", "#d946ef"),
        ],
        title="Planned and actual spending by category",
        gradient_prefix="plan-compare",
    )

    pill_classes = {
        "Under plan": "pass",
        "On plan": "pass",
        "Over plan": "fail",
        "No plan": "warn",
        "Not used": "neutral",
        "No activity": "neutral",
    }
    category_shares = display_share_pcts(
        [item.share_pct for item in analysis.categories]
    )
    near_names = {item.name for item in analysis.near_plan}
    rows: list[list[str]] = []
    row_classes: list[str] = []
    for item, share in zip(analysis.categories, category_shares):
        if item.difference_cents < 0:
            difference = f"-{money(-item.difference_cents / 100)}"
        else:
            difference = money(item.difference_cents / 100)
        category = (
            f"{escape_attr(item.name)}"
            f'<span class="plan-tag">{"Essential" if item.essential else "Flexible"}</span>'
        )
        if item.name in near_names:
            category += '<span class="plan-tag near">80%+ of plan</span>'
        rows.append(
            [
                category,
                money(item.planned_cents / 100),
                money(item.spent_cents / 100),
                difference,
                share_cell(share),
                f'<span class="pill {pill_classes[item.status]}">'
                f"{escape_attr(item.status)}</span>",
            ]
        )
        row_classes.append("over" if item.flagged else "")

    total_difference = analysis.planned_cents - analysis.spent_cents
    total_difference_text = (
        f"-{money(-total_difference / 100)}"
        if total_difference < 0
        else money(total_difference / 100)
    )
    rows.append(
        [
            "Total",
            money(analysis.planned_cents / 100),
            money(analysis.spent_cents / 100),
            total_difference_text,
            share_cell(100.0),
            "",
        ]
    )
    row_classes.append("total")

    bucket_shares = display_share_pcts(
        [analysis.essential_share_pct, 100.0 - analysis.essential_share_pct]
    )
    essential_rows = [
        ["Essential", money(analysis.essential_planned_cents / 100),
         money(analysis.essential_spent_cents / 100),
         share_cell(bucket_shares[0])],
        ["Flexible", money(analysis.flexible_planned_cents / 100),
         money(analysis.flexible_spent_cents / 100),
         share_cell(bucket_shares[1])],
    ]
    return f"""
  <section class="panel" id="analysis-categories"
    aria-labelledby="analysis-categories-title">
    <p class="eyebrow"><span class="section-no">07</span> Categories</p>
    <h2 id="analysis-categories-title">Where the money went</h2>
    <p class="lead">The first graph ranks your own categories by actual spending. The
      second puts each category's plan next to its actual spend on the same scale.</p>
    <h3>Spending by category</h3>
    {actual_chart}
    <h3>Plan next to actual</h3>
    {compare_chart}
    <h3>The numbers by category</h3>
    <p class="section-note">Every share is a share of recorded spending
      (KES {money(analysis.spent_cents / 100)}). Shares are rounded with the largest
      remainder, so the column adds up to exactly 100.0%.</p>
    {table([("Category", False), ("Planned KES", True), ("Spent KES", True),
            ("Planned minus spent", True), ("Share of recorded spending", True),
            ("Status", False)], rows, row_classes=row_classes)}
    <div class="plan-split">
      <div>
        <h3>Essential and flexible</h3>
        <p class="section-note">The split you chose while entering the categories.
          Shares are of recorded spending and also add up to 100.0%.</p>
        {table([("Bucket", False), ("Planned KES", True), ("Spent KES", True),
                ("Share of recorded spending", True)], essential_rows)}
      </div>
      <div>
        <h3>How to read it</h3>
        <p class="section-note">Planned minus spent is positive when a category still
          has money and negative when it is over. "No plan" means spending was recorded
          against a category with a zero planned amount. "Not used" is a planned category
          with no entries. Every figure comes from the values in this form.</p>
      </div>
    </div>
  </section>"""


def _recorded_stamp(value: datetime) -> str:
    iso = escape_attr(value.isoformat(timespec="minutes"))
    label = escape_attr(value.strftime("%d %b %Y, %H:%M"))
    return f'<time datetime="{iso}">{label}</time>'


def _plan_spending_panel(plan: object, analysis: object) -> str:
    rows = [
        [
            escape_attr(entry.category),
            escape_attr(entry.note or "—"),
            money(entry.amount_cents / 100),
        ]
        for entry in plan.spendings
    ]
    return f"""
  <section class="panel" id="analysis-spending"
    aria-labelledby="analysis-spending-title">
    <p class="eyebrow"><span class="section-no">08</span> Entries</p>
    <h2 id="analysis-spending-title">The spending behind the totals</h2>
    <p class="lead">In the order you entered them. These rows are the source of every
      category total and graph above.</p>
    <div class="table-meta">
      <span>{integer(len(rows))} entries</span>
      <span>KES {money(analysis.spent_cents / 100)} total</span>
      <span>Recorded {_recorded_stamp(analysis.recorded_at)}</span>
    </div>
    {table([("Category", False), ("Note", False),
            ("Amount KES", True)], rows)}
  </section>"""


def _plan_method_panel(plan: MoneyPlan) -> str:
    method_label = BUDGET_METHODS[plan.method]
    note = (
        f'<p class="method-note">{escape_attr(plan.method_note)}</p>'
        if plan.method_note
        else '<p class="section-note">No budgeting note was added.</p>'
    )
    return f"""
  <section class="panel" id="analysis-method" aria-labelledby="analysis-method-title">
    <p class="eyebrow"><span class="section-no">09</span> Method</p>
    <h2 id="analysis-method-title">How you planned</h2>
    <p class="plan-meta">
      <span>Method: <strong>{escape_attr(method_label)}</strong></span>
      <span>Period: <strong>{escape_attr(plan.period_label)}</strong></span>
    </p>
    {note}
    <p class="lead">The analysis does not score your budgeting method or recommend
      financial products. It only compares the categories and amounts you entered with
      the spending entries you recorded.</p>
  </section>"""


def _plan_receipt_panel(plan: MoneyPlan, analysis: PlanAnalysis) -> str:
    spent_categories = [
        item for item in analysis.ranked_categories if item.spent_cents
    ]
    shares = display_share_pcts([item.share_pct for item in spent_categories])
    lines = "".join(
        "<li>"
        f'<span class="receipt-item"><span class="receipt-name">'
        f"{escape_attr(item.name)}</span>"
        f'<span class="receipt-tag">{"Essential" if item.essential else "Flexible"}</span>'
        "</span>"
        '<span class="receipt-dots" aria-hidden="true"></span>'
        f'<span class="receipt-share">{percent(share)}</span>'
        f'<span class="receipt-amount">{money(item.spent_cents / 100)}</span>'
        "</li>"
        for item, share in zip(spent_categories, shares)
    )
    if not lines:
        lines = (
            '<li><span class="receipt-item"><span class="receipt-name">'
            "No recorded spending</span></span></li>"
        )
    if analysis.remaining_cents >= 0:
        balance_label = "Left unspent"
        balance_value = money(analysis.remaining_cents / 100)
    else:
        balance_label = "Over the money available"
        balance_value = f"-{money(-analysis.remaining_cents / 100)}"
    return f"""
  <section class="panel" id="analysis-receipt"
    aria-labelledby="analysis-receipt-title">
    <p class="eyebrow"><span class="section-no">06</span> Receipt</p>
    <h2 id="analysis-receipt-title">Your plan, itemised</h2>
    <p class="lead">A receipt for the same numbers as the analysis: every category you
      spent in, the planned total, the money available and the balance left.</p>
    <div class="receipt-wrap">
      <article class="receipt"
        aria-label="Money plan receipt for {escape_attr(plan.student_name)}">
        <span class="receipt-stamp" aria-hidden="true">Local<br>only</span>
        <header class="receipt-head">
          <span class="receipt-kicker">Student Spending Analytics</span>
          <strong class="receipt-title">Money plan receipt</strong>
          <span class="receipt-sub">One student &middot; plan figures &middot; KES</span>
        </header>
        <dl class="receipt-meta">
          <div><dt>Name</dt><dd>{escape_attr(plan.student_name)}</dd></div>
          <div><dt>Entries</dt><dd>{integer(len(plan.spendings))}</dd></div>
          <div><dt>Recorded</dt><dd>{_recorded_stamp(analysis.recorded_at)}</dd></div>
          <div><dt>Period</dt><dd>{escape_attr(plan.period_label)}</dd></div>
          <div><dt>Method</dt><dd>{escape_attr(BUDGET_METHODS[plan.method])}</dd></div>
        </dl>
        <div class="receipt-rule" aria-hidden="true"></div>
        <ul class="receipt-lines">{lines}</ul>
        <div class="receipt-rule" aria-hidden="true"></div>
        <dl class="receipt-totals">
          <div><dt>Planned total</dt><dd>{money(analysis.planned_cents / 100)}</dd></div>
          <div><dt>Recorded spending</dt><dd>{money(analysis.spent_cents / 100)}</dd></div>
          <div><dt>Money available ({escape_attr(plan.period_label.lower())})</dt>
            <dd>{money(analysis.money_available_cents / 100)}</dd></div>
          <div class="receipt-balance"><dt>{balance_label}</dt><dd>{balance_value}</dd></div>
        </dl>
        <p class="receipt-foot">Generated on this server &middot; not a financial document<br>
          planning figures only</p>
        <div class="receipt-barcode" aria-hidden="true"></div>
        <p class="receipt-code" aria-hidden="true">SSA &middot;
          {escape_attr(analysis.recorded_at.strftime("%d %b %Y"))} &middot;
          {escape_attr(analysis.recorded_at.strftime("%H:%M"))}</p>
      </article>
    </div>
    <p class="plan-section-note">To keep this receipt, print this page or choose
      &ldquo;Save as PDF&rdquo; in your browser. Nothing is uploaded or stored by the
      platform.</p>
  </section>"""


def _plan_snapshot_fields(
    draft: PlanDraft, *, category_rows: int, spending_rows: int
) -> str:
    """Repeat the submitted plan inside the coach form.

    The coach is a second form on the same page, so it cannot read the main
    form's fields without JavaScript. Hidden copies of the raw draft let the
    server re-validate the plan and answer from the same numbers.
    """
    fields: list[str] = []

    def hidden(name: str, value: str) -> None:
        fields.append(
            f'<input type="hidden" name="{escape_attr(name)}" '
            f'value="{escape_attr(value)}">'
        )

    hidden("student_name", draft.student_name)
    hidden("money_available", draft.money_available)
    hidden("period", draft.period)
    hidden("method", draft.method)
    hidden("method_note", draft.method_note)
    hidden("category_rows", str(category_rows))
    hidden("spending_rows", str(spending_rows))
    hidden("advice_ack", "yes")
    for number in range(1, category_rows + 1):
        row = draft.category(number)
        hidden(f"category_name_{number}", row.name)
        hidden(f"category_amount_{number}", row.planned)
        hidden(
            f"category_essential_{number}",
            "essential" if row.essential else "flexible",
        )
    for number in range(1, spending_rows + 1):
        row = draft.spending(number)
        hidden(f"spending_category_{number}", row.category)
        hidden(f"spending_amount_{number}", row.amount)
        hidden(f"spending_note_{number}", row.note)
    return "\n".join(fields)


COACH_TOPICS = (
    "Where can I cut spending?",
    "How can I save more?",
    "Is my plan balanced?",
    "What is left?",
    "What does the receipt time mean?",
)


def _plan_coach_panel(
    plan: MoneyPlan,
    analysis: PlanAnalysis,
    draft: PlanDraft,
    *,
    category_rows: int,
    spending_rows: int,
    coach_question: str,
    coach_reply: CoachReply | None,
) -> str:
    snapshot = _plan_snapshot_fields(
        draft, category_rows=category_rows, spending_rows=spending_rows
    )
    chips = "".join(
        '<button class="button ghost" type="submit" name="coach_topic" '
        f'value="{escape_attr(topic)}">{escape_attr(topic)}</button>'
        for topic in COACH_TOPICS
    )
    if coach_reply is not None:
        paragraphs = "".join(
            f"<p>{escape_attr(paragraph)}</p>"
            for paragraph in coach_reply.paragraphs
        )
        reply_html = (
            '<div class="coach-answer" role="status">'
            '<span class="coach-origin">Local rules &middot; no network</span>'
            f'<p class="coach-asked">You asked: '
            f"<span>{escape_attr(coach_reply.question)}</span></p>"
            f"{paragraphs}</div>"
        )
    else:
        reply_html = ""
    return f"""
  <section class="panel" id="coach" aria-labelledby="coach-title">
    <p class="eyebrow"><span class="section-no">10</span> Coach</p>
    <h2 id="coach-title">Ask the money coach</h2>
    <p class="lead">A local rule set, not an AI model. It reads only the plan you just
      submitted, answers with the same figures, and never sends anything off this
      machine.</p>
    <form class="coach-form" method="post" action="/plan#coach"
      accept-charset="utf-8">
      {csrf_field()}
      {snapshot}
      <input type="hidden" name="action" value="ask_coach">
      <div class="coach-question">
        <div class="field">
          <label for="coach_question">Your question</label>
          <input id="coach_question" name="coach_question" type="text"
            maxlength="{MAX_QUESTION_LENGTH}"
            value="{escape_attr(coach_question)}"
            placeholder="e.g. Where can I cut spending?" autocomplete="off">
        </div>
        <button class="button primary" type="submit">Ask the coach</button>
      </div>
      <div class="coach-chips" aria-label="Quick questions">{chips}</div>
    </form>
    {reply_html}
    <p class="plan-section-note">The coach matches a few fixed topics and fills in the
      numbers from this analysis. It is not financial advice.</p>
  </section>"""


def _plan_analysis_sections(
    plan: MoneyPlan,
    analysis: PlanAnalysis,
    draft: PlanDraft,
    *,
    category_rows: int,
    spending_rows: int,
    coach_question: str = "",
    coach_reply: CoachReply | None = None,
) -> str:
    summary = _plan_summary(plan, analysis)
    return f"""
  <section class="panel" id="analysis" aria-labelledby="analysis-title">
    <p class="eyebrow"><span class="section-no">05</span> Analysis</p>
    <h2 id="analysis-title">What the numbers say</h2>
    <p class="lead">{escape_attr(summary)}</p>
    {_plan_cards(plan, analysis)}
    {_plan_banners(plan, analysis)}
    <h3>What stands out</h3>
    {_plan_insights(plan, analysis)}
    {_plan_suggestions(plan, analysis)}
    <p class="plan-section-note">This analysis was generated in this page from the
      values above. It is not saved as a separate link or file.</p>
    <div class="plan-actions">
      <a class="button primary" href="#analysis-receipt">Open the receipt</a>
      <a class="button ghost" href="#coach">Ask the coach</a>
      <a class="button ghost" href="#money">Change the numbers</a>
    </div>
    <form class="plan-export" method="post" action="/plan.csv" accept-charset="utf-8">
      {csrf_field()}
      {_plan_snapshot_fields(draft, category_rows=category_rows, spending_rows=spending_rows)}
      <button class="button ghost" type="submit">Download this plan as CSV</button>
    </form>
  </section>
  {_plan_receipt_panel(plan, analysis)}
  {_plan_category_panel(plan, analysis)}
  {_plan_spending_panel(plan, analysis)}
  {_plan_method_panel(plan)}
  {_plan_coach_panel(
      plan,
      analysis,
      draft,
      category_rows=category_rows,
      spending_rows=spending_rows,
      coach_question=coach_question,
      coach_reply=coach_reply,
  )}
"""


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    """Open the warehouse so a bug in a handler cannot modify it."""
    uri = db_path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _cookie_value(header: str, name: str) -> str:
    for part in header.split(";"):
        key, separator, value = part.strip().partition("=")
        if separator and key == name:
            return value.strip()
    return ""


def _session_cookie(token: str, *, secure: bool = False) -> tuple[str, str]:
    return (
        "Set-Cookie",
        f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; "
        f"{'Secure; ' if secure else ''}Max-Age={SESSION_SECONDS}",
    )


def _cleared_cookie(*, secure: bool = False) -> tuple[str, str]:
    return (
        "Set-Cookie",
        f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; "
        f"{'Secure; ' if secure else ''}Max-Age=0",
    )


class _AuthRequestError(ValueError):
    """A malformed sign-in or sign-up request."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class _AttemptLimiter:
    """Slow down repeated sign-in failures from one address."""

    def __init__(self, limit: int = AUTH_ATTEMPT_LIMIT,
                 window: float = AUTH_ATTEMPT_WINDOW_SECONDS):
        self.limit = limit
        self.window = window
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str) -> list[float]:
        cutoff = time.monotonic() - self.window
        recent = [stamp for stamp in self._failures.get(key, ()) if stamp > cutoff]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)
        return recent

    def blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._recent(key)) >= self.limit

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._recent(key)
            self._failures.setdefault(key, []).append(time.monotonic())

    def clear(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], *, db_path: Path, report_path: Path,
                 accounts_path: Path | str | None = None,
                 secure_cookies: bool = False):
        super().__init__(address, DashboardHandler)
        self.db_path = db_path
        self.report_path = report_path
        self.accounts = AccountStore(accounts_path or config.ACCOUNTS_DB_PATH)
        self.login_attempts = _AttemptLimiter()
        self.secure_cookies = secure_cookies
        self.pending_recovery: dict[int, str] = {}
        self.recovery_lock = threading.Lock()


class DashboardHandler(BaseHTTPRequestHandler):
    server: DashboardServer
    server_version = f"PlanItDashboard/{__version__}"
    sys_version = ""
    timeout = 30

    def log_message(self, format: str, *args: object) -> None:
        logger.debug("%s - %s", self.address_string(), format % args)

    def do_GET(self) -> None:  # noqa: N802 - required by http.server
        self._dispatch(head_only=False)

    def do_HEAD(self) -> None:  # noqa: N802 - required by http.server
        self._dispatch(head_only=True)

    def do_POST(self) -> None:  # noqa: N802 - required by http.server
        path = urllib.parse.urlsplit(self.path).path
        self._set_csrf_context()
        try:
            if path in ("/login", "/signup", "/logout", "/reset"):
                if self.command != "POST":
                    self._method_not_allowed()
                elif path == "/login":
                    self._handle_login()
                elif path == "/signup":
                    self._handle_signup()
                elif path == "/reset":
                    self._handle_reset()
                else:
                    self._handle_logout()
            elif path.startswith("/account/"):
                kind = path.removeprefix("/account/")
                if self.command != "POST" or kind not in {
                    "consent", "recovery", "password", "export", "delete"
                }:
                    self._method_not_allowed()
                else:
                    self._handle_account_action(kind)
            elif path == "/upload":
                self._create_analysis()
            elif path == "/plan":
                self._create_plan()
            elif path == "/plan.csv":
                self._handle_plan_csv()
            elif path == "/delete-analysis":
                self._handle_delete_analysis()
            else:
                self._method_not_allowed()
        except Exception:  # noqa: BLE001 - one bad request must not stop the server
            logger.exception("unexpected POST failure for %s", path)
            action = {
                "/plan": "/plan",
                "/plan.csv": "/plan",
                "/upload": "/upload",
                "/login": "/login",
                "/signup": "/signup",
                "/logout": "/login",
                "/reset": "/reset",
                "/delete-analysis": "/upload",
            }.get(path, "/account" if path.startswith("/account") else "/")
            self._safe_send(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                _error_document(
                    "The request could not be completed",
                    "An unexpected error interrupted this request. Check the server "
                    "log, then try again.",
                    action_href=action,
                    action_label="Back to the form",
                ),
                head_only=False,
            )

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST

    def _method_not_allowed(self) -> None:
        body = _error_document(
            "Read-only dashboard",
            "This address only answers GET requests. Use the filter form on the "
            "dashboard, or submit the money-plan form from /plan.",
        )
        self._send(HTTPStatus.METHOD_NOT_ALLOWED, body,
                   headers=[("Allow", "GET, HEAD")])

    def _no_content(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; "
            "form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
        )
        if self.server.secure_cookies:
            self.send_header(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )

    def _send(self, status: int, body: str, *, headers: list[tuple[str, str]] | None = None,
              content_type: str = "text/html; charset=utf-8",
              head_only: bool = False, cache_control: str = "no-store") -> None:
        self._send_payload(
            status,
            body.encode("utf-8"),
            headers=headers,
            content_type=content_type,
            head_only=head_only,
            cache_control=cache_control,
        )

    def _send_payload(self, status: int, payload: bytes, *,
                      headers: list[tuple[str, str]] | None = None,
                      content_type: str = "text/html; charset=utf-8",
                      head_only: bool = False,
                      cache_control: str = "no-store") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", cache_control)
        self._security_headers()
        for name, value in headers or ():
            self.send_header(name, value)
        self.end_headers()
        if not head_only:
            self.wfile.write(payload)

    def _logo_asset(self, *, head_only: bool) -> None:
        try:
            payload = _logo_bytes()
        except OSError:
            logger.exception("Plan It logo is missing from the package")
            body = _error_document(
                "Logo unavailable",
                "The Plan It logo could not be read from the installed package.",
            )
            self._send(HTTPStatus.NOT_FOUND, body, head_only=head_only)
            return
        self._send_payload(
            HTTPStatus.OK,
            payload,
            content_type="image/jpeg",
            head_only=head_only,
            cache_control="public, max-age=86400",
        )

    def _upload_page(self, query: dict[str, list[str]], *, head_only: bool) -> None:
        account = self._require_account(_safe_next(self.path, "/upload"))
        if account is None:
            return
        requested = workspace_for(_first(query, "analysis"))
        current = (
            requested
            if requested is not None and requested.account_id == account.account_id
            else None
        )
        notice = ""
        if _first(query, "deleted") == "1":
            notice = "That analysis and its files were removed from this machine."
        elif _first(query, "missing") == "1":
            notice = "That analysis is no longer available."
        body = render_upload_page(
            analyses=list_analyses(account_id=account.account_id),
            current_analysis=current,
            account=account,
            notice=notice,
        )
        self._send(HTTPStatus.OK, body, head_only=head_only)

    def _plan_page(self, query: dict[str, list[str]], *, head_only: bool) -> None:
        account = self._require_account("/plan")
        if account is None:
            return
        self._send(
            HTTPStatus.OK,
            render_plan_page(account=account),
            head_only=head_only,
        )

    def _login_page(self, query: dict[str, list[str]], *, head_only: bool) -> None:
        next_path = _safe_next(_first(query, "next"))
        if self._current_account() is not None:
            self._redirect(next_path)
            return
        notice = ""
        if _first(query, "signedout") == "1":
            notice = "You are signed out. Sign in again to use the planner or uploads."
        elif _first(query, "reset") == "1":
            notice = "Password reset complete. Sign in with the new password."
        elif _first(query, "changed") == "1":
            notice = "Password changed. Sign in again with the new password."
        elif _first(query, "deleted") == "1":
            notice = (
                "Account deleted. Its account record, sessions and uploads were "
                "removed from this machine."
            )
        self._send(
            HTTPStatus.OK,
            render_login_page(next_path=next_path, notice=notice),
            head_only=head_only,
        )

    def _signup_page(self, query: dict[str, list[str]], *, head_only: bool) -> None:
        next_path = _safe_next(_first(query, "next"))
        if self._current_account() is not None:
            self._redirect(next_path)
            return
        self._send(
            HTTPStatus.OK,
            render_signup_page(next_path=next_path),
            head_only=head_only,
        )

    def _welcome_page(self, query: dict[str, list[str]], *, head_only: bool) -> None:
        # The artificial loading screen was removed: sign-in lands on the page the
        # student asked for. The old address redirects so saved links still work.
        next_path = _safe_next(_first(query, "next"))
        account = self._require_account(next_path)
        if account is None:
            return
        self._redirect(next_path)

    def _client_key(self) -> str:
        """Rate-limit key: the proxy-forwarded client when explicitly trusted."""
        remote = str(self.client_address[0]) if self.client_address else "local"
        if not config.TRUST_PROXY:
            return remote
        forwarded = self.headers.get("X-Forwarded-For", "")
        candidate = forwarded.split(",", 1)[0].strip()
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            return remote

    def _session_token(self) -> str:
        return _cookie_value(self.headers.get("Cookie", ""), SESSION_COOKIE)

    def _current_account(self) -> Account | None:
        token = self._session_token()
        if not token:
            return None
        return self.server.accounts.account_for_token(token)

    def _redirect(
        self,
        location: str,
        *,
        headers: list[tuple[str, str]] | None = None,
        close: bool = False,
    ) -> None:
        extra = list(headers or ())
        if close:
            extra.append(("Connection", "close"))
            self.close_connection = True
        self._send(
            HTTPStatus.SEE_OTHER,
            "",
            headers=[("Location", location), *extra],
        )

    def _require_account(self, next_path: str, *, close: bool = False) -> Account | None:
        account = self._current_account()
        if account is None:
            target = "/login?" + urllib.parse.urlencode({"next": next_path})
            self._redirect(target, close=close)
        return account

    def _blocked_request(self, message: str, action: str, label: str) -> None:
        self._send(
            HTTPStatus.FORBIDDEN,
            _error_document(
                "Request blocked",
                message,
                action_href=action,
                action_label=label,
                eyebrow="Account",
            ),
            headers=[("Connection", "close")],
        )
        self.close_connection = True

    def _set_csrf_context(self) -> None:
        token = self._session_token()
        value = self.server.accounts.csrf_for_token(token) if token else ""
        _CSRF_VALUE.set(value)

    def _csrf_valid(self, form: dict[str, list[str]]) -> bool:
        expected = _CSRF_VALUE.get()
        supplied = _first(form, "csrf")
        return (
            bool(expected)
            and bool(supplied)
            and hmac.compare_digest(expected, supplied)
        )

    def _require_csrf(
        self,
        form: dict[str, list[str]],
        action: str,
        label: str,
        *,
        eyebrow: str = "Account",
    ) -> bool:
        if self._csrf_valid(form):
            return True
        self._send(
            HTTPStatus.FORBIDDEN,
            _error_document(
                "Request blocked",
                "That form has expired or did not come from this page. Reload "
                "the page and submit it again.",
                action_href=action,
                action_label=label,
                eyebrow=eyebrow,
            ),
            headers=[("Connection", "close")],
        )
        self.close_connection = True
        return False

    def _read_auth_form(self) -> dict[str, list[str]]:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise _AuthRequestError(
                "The browser did not send a Content-Length header.", status=411
            )
        try:
            length = int(raw_length)
        except ValueError:
            raise _AuthRequestError("The form length is not valid.") from None
        if length <= 0:
            raise _AuthRequestError("The form was empty.")
        if length > MAX_AUTH_REQUEST_BYTES:
            raise _AuthRequestError(
                "That form is larger than the server accepts.", status=413
            )
        media_type = (
            self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        )
        if media_type != "application/x-www-form-urlencoded":
            raise _AuthRequestError(
                "Submit this form from its own page.", status=415
            )
        body = self.rfile.read(length)
        if len(body) != length:
            raise _AuthRequestError("The form ended before all bytes arrived.")
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            raise _AuthRequestError("The form must be UTF-8 text.") from None
        try:
            return urllib.parse.parse_qs(
                text, keep_blank_values=True, max_num_fields=12
            )
        except ValueError:
            raise _AuthRequestError("The form has too many fields.") from None

    def _handle_login(self) -> None:
        if not self._same_origin():
            self._blocked_request(
                "Sign in from this dashboard's own form.",
                "/login",
                "Back to sign in",
            )
            return
        next_path = "/plan"
        email = ""
        try:
            form = self._read_auth_form()
            next_path = _safe_next(_first(form, "next"))
            email = _first(form, "email").strip()
            password = _first(form, "password")
        except _AuthRequestError as error:
            self._send(
                error.status,
                render_login_page(
                    next_path=next_path, errors=[str(error)]
                ),
                headers=[("Connection", "close")],
            )
            self.close_connection = True
            return

        key = self._client_key()
        if self.server.login_attempts.blocked(key):
            self._send(
                HTTPStatus.TOO_MANY_REQUESTS,
                render_login_page(
                    email=email,
                    next_path=next_path,
                    errors=[
                        "Too many sign-in attempts from this address. Wait a few "
                        "minutes and try again."
                    ],
                ),
                headers=[
                    ("Retry-After", str(AUTH_ATTEMPT_WINDOW_SECONDS)),
                    ("Connection", "close"),
                ],
            )
            self.close_connection = True
            return

        if not email or not password:
            self.server.login_attempts.record_failure(key)
            self._send(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                render_login_page(
                    email=email,
                    next_path=next_path,
                    errors=["Enter both the email and the password."],
                ),
            )
            return

        account = self.server.accounts.authenticate(email, password)
        if account is None:
            self.server.login_attempts.record_failure(key)
            logger.info("sign-in failed for an unknown or mismatched account")
            self._send(
                HTTPStatus.UNAUTHORIZED,
                render_login_page(
                    email=email,
                    next_path=next_path,
                    errors=[
                        "That email and password did not match. Check both and try "
                        "again, or reset the password with your recovery code."
                    ],
                ),
            )
            return

        self.server.login_attempts.clear(key)
        token = self.server.accounts.create_session(account.account_id)
        self._redirect(
            next_path,
            headers=[_session_cookie(token, secure=self.server.secure_cookies)],
        )

    def _handle_signup(self) -> None:
        if not self._same_origin():
            self._blocked_request(
                "Create an account from this dashboard's own form.",
                "/signup",
                "Back to the form",
            )
            return
        next_path = "/plan"
        try:
            form = self._read_auth_form()
        except _AuthRequestError as error:
            self._send(
                error.status,
                render_signup_page(next_path=next_path, errors=[str(error)]),
                headers=[("Connection", "close")],
            )
            self.close_connection = True
            return

        next_path = _safe_next(_first(form, "next"))
        raw_name = _first(form, "display_name").strip()
        raw_email = _first(form, "email").strip()
        password = _first(form, "password")
        confirm = _first(form, "confirm")
        privacy_acknowledged = _first(form, "privacy_ack") == "yes"

        name = raw_name
        email = raw_email
        errors: list[str] = []
        try:
            name = validate_display_name(raw_name)
        except AccountError as error:
            errors.append(str(error))
        try:
            email = validate_email(raw_email)
        except AccountError as error:
            errors.append(str(error))
        try:
            validate_password(password)
        except AccountError as error:
            errors.append(str(error))
        if password != confirm:
            errors.append("The two passwords do not match.")
        if not privacy_acknowledged:
            errors.append(
                "Read and agree to the privacy notice and terms before creating "
                "the account."
            )

        if errors:
            self._send(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                render_signup_page(
                    display_name=raw_name,
                    email=raw_email,
                    next_path=next_path,
                    errors=errors,
                ),
            )
            return

        try:
            account = self.server.accounts.create_account(
                name, email, password, consented=True
            )
        except AccountError as error:
            self._send(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                render_signup_page(
                    display_name=raw_name,
                    email=raw_email,
                    next_path=next_path,
                    errors=[str(error)],
                ),
            )
            return

        token = self.server.accounts.create_session(account.account_id)
        logger.info("created account %s", account.account_id)
        # The recovery code is shown once on the account page. Only its digest is
        # written to disk, so it is held in memory until that page renders.
        code = self.server.accounts.generate_recovery_code(
            account.account_id, password
        )
        if code:
            self._stash_recovery_code(account.account_id, code)
        self._redirect(
            "/account?new=1",
            headers=[_session_cookie(token, secure=self.server.secure_cookies)],
        )

    def _stash_recovery_code(self, account_id: int, code: str) -> None:
        with self.server.recovery_lock:
            self.server.pending_recovery[account_id] = code

    def _take_recovery_code(self, account_id: int) -> str:
        with self.server.recovery_lock:
            return self.server.pending_recovery.pop(account_id, "")

    def _account_page(self, query: dict[str, list[str]], *, head_only: bool) -> None:
        account = self._require_account("/account")
        if account is None:
            return
        new_code = ""
        if _first(query, "new") == "1" or _first(query, "recovery") == "1":
            new_code = self._take_recovery_code(account.account_id)
        notice = ""
        if _first(query, "consent") == "1":
            notice = "Privacy consent was recorded for this policy version."
        self._send(
            HTTPStatus.OK,
            render_account_page(account, new_code=new_code, notice=notice),
            head_only=head_only,
        )

    def _reset_page(self, query: dict[str, list[str]], *, head_only: bool) -> None:
        if self._current_account() is not None:
            self._redirect("/account")
            return
        self._send(
            HTTPStatus.OK,
            render_reset_page(email=_first(query, "email")),
            head_only=head_only,
        )

    def _legal_page(self, title: str, body: str, *, head_only: bool) -> None:
        self._send(
            HTTPStatus.OK,
            render_legal_page(title, body),
            head_only=head_only,
        )

    def _health(self, *, head_only: bool) -> None:
        checks = {"warehouse": False, "accounts": False}
        try:
            connection = self._open()
            try:
                connection.execute("SELECT 1 FROM transactions LIMIT 1").fetchone()
            finally:
                connection.close()
            checks["warehouse"] = True
        except (sqlite3.Error, OSError):
            logger.exception("health check could not read the warehouse")
        checks["accounts"] = self.server.accounts.path.is_file()
        healthy = all(checks.values())
        payload = json.dumps(
            {
                "status": "ok" if healthy else "degraded",
                "version": __version__,
                "checks": checks,
            },
            sort_keys=True,
        )
        self._send(
            HTTPStatus.OK if healthy else HTTPStatus.SERVICE_UNAVAILABLE,
            payload,
            content_type="application/json; charset=utf-8",
            head_only=head_only,
        )

    def _delete_analysis_page(
        self, query: dict[str, list[str]], *, head_only: bool
    ) -> None:
        account = self._require_account("/upload")
        if account is None:
            return
        analysis = workspace_for(_first(query, "analysis"))
        if analysis is None or analysis.account_id != account.account_id:
            self._redirect("/upload?missing=1")
            return
        self._send(
            HTTPStatus.OK,
            render_delete_analysis_page(analysis),
            head_only=head_only,
        )

    def _handle_reset(self) -> None:
        if not self._same_origin():
            self._blocked_request(
                "Reset the password from this dashboard's own form.",
                "/reset",
                "Back to the reset form",
            )
            return
        try:
            form = self._read_auth_form()
        except _AuthRequestError as error:
            self._send(
                error.status,
                render_reset_page(errors=[str(error)]),
                headers=[("Connection", "close")],
            )
            self.close_connection = True
            return

        email = _first(form, "email").strip()
        code = _first(form, "recovery_code")
        password = _first(form, "password")
        confirm = _first(form, "confirm")
        errors: list[str] = []
        try:
            validate_email(email)
        except AccountError as error:
            errors.append(str(error))
        try:
            validate_password(password)
        except AccountError as error:
            errors.append(str(error))
        if password != confirm:
            errors.append("The two passwords do not match.")
        if not code.strip():
            errors.append("Enter the one-time recovery code.")
        if errors:
            self._send(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                render_reset_page(email=email, errors=errors),
            )
            return

        key = "account:" + self._client_key()
        if self.server.login_attempts.blocked(key):
            self._send(
                HTTPStatus.TOO_MANY_REQUESTS,
                render_reset_page(
                    email=email,
                    errors=[
                        "Too many recovery attempts from this address. Wait a few "
                        "minutes and try again."
                    ],
                ),
                headers=[
                    ("Retry-After", str(AUTH_ATTEMPT_WINDOW_SECONDS)),
                    ("Connection", "close"),
                ],
            )
            self.close_connection = True
            return

        if not self.server.accounts.reset_password(email, code, password):
            self.server.login_attempts.record_failure(key)
            logger.info("password reset rejected for an unknown email or code")
            self._send(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                render_reset_page(
                    email=email,
                    errors=[
                        "That email and recovery code did not match, or the code was "
                        "already used. Check both and try again."
                    ],
                ),
            )
            return

        self.server.login_attempts.clear(key)
        logger.info("password reset with a recovery code")
        self._redirect("/login?reset=1")

    def _handle_account_action(self, kind: str) -> None:
        account = self._require_account("/account", close=True)
        if account is None:
            return
        if not self._same_origin():
            self._blocked_request(
                "Manage the account from this dashboard's own form.",
                "/account",
                "Back to the account page",
            )
            return
        try:
            form = self._read_auth_form()
        except _AuthRequestError as error:
            self._send(
                error.status,
                render_account_page(account, errors=[str(error)]),
                headers=[("Connection", "close")],
            )
            self.close_connection = True
            return
        if not self._require_csrf(
            form, "/account", "Back to the account page"
        ):
            return

        key = "account:" + self._client_key()
        if self.server.login_attempts.blocked(key):
            self._send(
                HTTPStatus.TOO_MANY_REQUESTS,
                render_account_page(
                    account,
                    errors=[
                        "Too many password attempts from this address. Wait a few "
                        "minutes and try again."
                    ],
                ),
                headers=[
                    ("Retry-After", str(AUTH_ATTEMPT_WINDOW_SECONDS)),
                    ("Connection", "close"),
                ],
            )
            self.close_connection = True
            return

        if kind == "consent":
            if _first(form, "privacy_ack") != "yes":
                self._send(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    render_account_page(
                        account,
                        errors=["Tick the consent box to record this version."],
                    ),
                )
                return
            self.server.accounts.set_consent(account.account_id)
            self._redirect("/account?consent=1")
            return

        if kind == "recovery":
            code = self.server.accounts.generate_recovery_code(
                account.account_id, _first(form, "current_password")
            )
            if code is None:
                self.server.login_attempts.record_failure(key)
                self._send(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    render_account_page(
                        account,
                        errors=["That password did not match. Try again."],
                    ),
                )
                return
            self.server.login_attempts.clear(key)
            self._stash_recovery_code(account.account_id, code)
            self._redirect("/account?recovery=1")
            return

        if kind == "password":
            new_password = _first(form, "new_password")
            confirm = _first(form, "confirm")
            errors: list[str] = []
            try:
                validate_password(new_password)
            except AccountError as error:
                errors.append(str(error))
            if new_password != confirm:
                errors.append("The two new passwords do not match.")
            if errors:
                self._send(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    render_account_page(account, errors=errors),
                )
                return
            changed = self.server.accounts.change_password(
                account.account_id, _first(form, "current_password"), new_password
            )
            if not changed:
                self.server.login_attempts.record_failure(key)
                self._send(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    render_account_page(
                        account,
                        errors=["That current password did not match. Try again."],
                    ),
                )
                return
            self.server.login_attempts.clear(key)
            logger.info("password changed for account %s", account.account_id)
            self._redirect(
                "/login?changed=1",
                headers=[_cleared_cookie(secure=self.server.secure_cookies)],
            )
            return

        if kind == "export":
            if not self.server.accounts.verify_account_password(
                account.account_id, _first(form, "password")
            ):
                self.server.login_attempts.record_failure(key)
                self._send(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    render_account_page(
                        account,
                        errors=["That password did not match. Try again."],
                    ),
                )
                return
            self.server.login_attempts.clear(key)
            uploads = list_analyses(limit=None, account_id=account.account_id)
            payload = {
                "service": "Plan It",
                "exported_at": config.utc_now(),
                "policy_version": legal.POLICY_VERSION,
                "disclaimer": legal.DISCLAIMER,
                "account": {
                    "display_name": account.display_name,
                    "email": account.email,
                    "created_at": account.created_at,
                    "consent_at": account.consent_at,
                    "consent_policy_version": account.policy_version,
                    "recovery_code_configured": account.recovery_configured,
                },
                "uploads": [
                    {
                        "analysis_id": item.analysis_id,
                        "title": item.title,
                        "created_at": item.created_at,
                        "status": item.status,
                        "rows_accepted": item.rows_accepted,
                    }
                    for item in uploads
                ],
                "not_exported": (
                    "Passwords and recovery-code digests are never exported. Money "
                    "plans are not stored, so there is no plan history to export."
                ),
            }
            body = json.dumps(payload, indent=2, ensure_ascii=False)
            self._send_payload(
                HTTPStatus.OK,
                body.encode("utf-8"),
                headers=[
                    (
                        "Content-Disposition",
                        'attachment; filename="plan-it-account-export.json"',
                    )
                ],
                content_type="application/json; charset=utf-8",
            )
            return

        if kind == "delete":
            if _first(form, "confirm_delete") != "yes":
                self._send(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    render_account_page(
                        account,
                        errors=["Tick the confirmation box to delete the account."],
                    ),
                )
                return
            if not self.server.accounts.verify_account_password(
                account.account_id, _first(form, "password")
            ):
                self.server.login_attempts.record_failure(key)
                self._send(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    render_account_page(
                        account,
                        errors=["That password did not match. Try again."],
                    ),
                )
                return
            self.server.login_attempts.clear(key)
            for item in list_analyses(limit=None, account_id=account.account_id):
                delete_analysis(item.analysis_id, account_id=account.account_id)
            self.server.accounts.delete_account(account.account_id)
            logger.info("account %s deleted", account.account_id)
            self._redirect(
                "/login?deleted=1",
                headers=[_cleared_cookie(secure=self.server.secure_cookies)],
            )
            return

        self._redirect("/account")

    def _handle_delete_analysis(self) -> None:
        account = self._require_account("/upload", close=True)
        if account is None:
            return
        if not self._same_origin():
            self._blocked_request(
                "Delete an upload from this dashboard's own page.",
                "/upload",
                "Back to uploads",
            )
            return
        try:
            form = self._read_auth_form()
        except _AuthRequestError as error:
            self._send(error.status, _error_document(
                "Delete not accepted", str(error), action_href="/upload"
            ), headers=[("Connection", "close")])
            self.close_connection = True
            return
        if not self._require_csrf(
            form, "/upload", "Back to uploads", eyebrow="Upload"
        ):
            return
        analysis_id = _first(form, "analysis_id")
        if not delete_analysis(analysis_id, account_id=account.account_id):
            self._send(
                HTTPStatus.NOT_FOUND,
                _error_document(
                    "Analysis not found",
                    "That analysis is not available or belongs to another account.",
                    action_href="/upload",
                ),
            )
            return
        self._redirect("/upload?deleted=1")

    def _handle_plan_csv(self) -> None:
        account = self._require_account("/plan", close=True)
        if account is None:
            return
        if not self._same_origin():
            self._blocked_request(
                "Export the plan from this dashboard's own form.",
                "/plan",
                "Back to the money plan",
            )
            return
        try:
            body = self._read_plan_body()
            form = parse_form(self.headers.get("Content-Type", ""), body)
        except PlanRequestError as error:
            self._send(
                error.status,
                _error_document(
                    "Plan not accepted",
                    str(error),
                    action_href="/plan",
                    action_label="Back to the money plan",
                    eyebrow="Money plan",
                ),
            )
            return
        if not self._require_csrf(
            form, "/plan", "Back to the money plan", eyebrow="Money plan"
        ):
            return
        category_rows = _form_row_count(
            form, "category_rows", default=CATEGORY_ROWS, maximum=MAX_CATEGORIES
        )
        spending_rows = _form_row_count(
            form, "spending_rows", default=SPENDING_ROWS, maximum=MAX_SPENDINGS
        )
        draft = read_draft(
            form, category_rows=category_rows, spending_rows=spending_rows
        )
        plan, errors = validate_draft(draft)
        if plan is None:
            self._send(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                render_plan_page(
                    draft=draft,
                    errors=errors,
                    category_rows=category_rows,
                    spending_rows=spending_rows,
                    account=account,
                ),
            )
            return
        analysis = analyse(plan, recorded_at=datetime.now().astimezone())
        filename = (
            f"plan-it-{plan.period}-{analysis.recorded_at.strftime('%Y-%m-%d')}.csv"
        )
        self._send(
            HTTPStatus.OK,
            render_plan_csv(plan, analysis),
            headers=[("Content-Disposition", f'attachment; filename="{filename}"')],
            content_type="text/csv; charset=utf-8",
        )

    def _handle_logout(self) -> None:
        if not self._same_origin():
            self._blocked_request(
                "Sign out from this dashboard's own form.",
                "/plan",
                "Back to the planner",
            )
            return
        token = self._session_token()
        if token and self.server.accounts.account_for_token(token) is not None:
            try:
                form = self._read_auth_form()
            except _AuthRequestError as error:
                self._send(
                    error.status,
                    _error_document(
                        "Sign out not accepted",
                        str(error),
                        action_href="/account",
                        action_label="Back to the account page",
                    ),
                    headers=[("Connection", "close")],
                )
                self.close_connection = True
                return
            if not self._require_csrf(
                form, "/account", "Back to the account page"
            ):
                return
        if token:
            self.server.accounts.delete_session(token)
        self._redirect(
            "/login?signedout=1",
            headers=[_cleared_cookie(secure=self.server.secure_cookies)],
            close=True,
        )

    def _create_plan(self) -> None:
        account = self._require_account("/plan", close=True)
        if account is None:
            return
        if not self._same_origin():
            self._send(
                HTTPStatus.FORBIDDEN,
                _error_document(
                    "Request blocked",
                    "Money plans must be submitted from this dashboard's own form.",
                    action_href="/plan",
                    action_label="Back to the money plan",
                    eyebrow="Money plan",
                ),
            )
            return
        try:
            body = self._read_plan_body()
            form = parse_form(self.headers.get("Content-Type", ""), body)
        except PlanRequestError as error:
            logger.info("plan request rejected: %s", error)
            self._send(
                error.status,
                _error_document(
                    "Plan not accepted",
                    str(error),
                    action_href="/plan",
                    action_label="Back to the money plan",
                    eyebrow="Money plan",
                ),
            )
            return

        if not self._require_csrf(
            form, "/plan", "Back to the money plan", eyebrow="Money plan"
        ):
            return
        category_rows = _form_row_count(
            form, "category_rows", default=CATEGORY_ROWS, maximum=MAX_CATEGORIES
        )
        spending_rows = _form_row_count(
            form, "spending_rows", default=SPENDING_ROWS, maximum=MAX_SPENDINGS
        )
        action = _first(form, "action")
        if action == "ask_coach":
            draft = read_draft(
                form, category_rows=category_rows, spending_rows=spending_rows
            )
            plan, errors = validate_draft(draft)
            if plan is None:
                self._send(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    render_plan_page(
                        draft=draft,
                        errors=errors,
                        category_rows=category_rows,
                        spending_rows=spending_rows,
                        account=account,
                    ),
                )
                return
            analysis = analyse(plan, recorded_at=datetime.now().astimezone())
            typed = _first(form, "coach_question").strip()
            # A quick-question button is the most recent action, so it wins over
            # text left in the box by the previous answer.
            question = _first(form, "coach_topic").strip() or typed
            self._send(
                HTTPStatus.OK,
                render_plan_page(
                    draft=draft,
                    plan=plan,
                    analysis=analysis,
                    coach_question=typed,
                    coach_reply=coach_answer(question, plan, analysis),
                    category_rows=category_rows,
                    spending_rows=spending_rows,
                    account=account,
                ),
            )
            return
        if action == "add_category":
            category_rows = min(category_rows + 1, MAX_CATEGORIES)
        elif action == "add_spending":
            spending_rows = min(spending_rows + 1, MAX_SPENDINGS)
        if action in ("add_category", "add_spending"):
            draft = read_draft(
                form, category_rows=category_rows, spending_rows=spending_rows
            )
            self._send(
                HTTPStatus.OK,
                render_plan_page(
                    draft=draft,
                    category_rows=category_rows,
                    spending_rows=spending_rows,
                    new_category_row=category_rows if action == "add_category" else None,
                    new_spending_row=spending_rows if action == "add_spending" else None,
                    account=account,
                ),
            )
            return

        draft = read_draft(
            form, category_rows=category_rows, spending_rows=spending_rows
        )
        plan, errors = validate_draft(draft)
        if plan is None:
            self._send(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                render_plan_page(
                    draft=draft,
                    errors=errors,
                    category_rows=category_rows,
                    spending_rows=spending_rows,
                    account=account,
                ),
            )
            return

        self._send(
            HTTPStatus.OK,
            render_plan_page(
                draft=draft,
                plan=plan,
                analysis=analyse(plan, recorded_at=datetime.now().astimezone()),
                category_rows=category_rows,
                spending_rows=spending_rows,
                account=account,
            ),
        )

    def _read_plan_body(self) -> bytes:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise PlanRequestError(
                "The browser did not send a Content-Length header.", status=411
            )
        try:
            length = int(raw_length)
        except ValueError:
            raise PlanRequestError("The form length is not valid.") from None
        if length <= 0:
            raise PlanRequestError("The plan form was empty.")
        if length > MAX_PLAN_REQUEST_BYTES:
            raise PlanRequestError(
                "The plan form is larger than the allowed limit.", status=413
            )
        body = self.rfile.read(length)
        if len(body) != length:
            raise PlanRequestError("The form ended before all bytes arrived.")
        return body

    def _create_analysis(self) -> None:
        account = self._require_account("/upload", close=True)
        if account is None:
            return
        if not self._same_origin():
            self._send(
                HTTPStatus.FORBIDDEN,
                _error_document(
                    "Request blocked",
                    "Uploads must come from this dashboard's own page.",
                    action_href="/upload",
                ),
            )
            return
        title = ""
        try:
            body = self._read_upload_body()
            content_type = self.headers.get("Content-Type", "")
            bundle = parse_upload(content_type, body)
            title = bundle.title
            if not self._require_csrf(
                {"csrf": [bundle.csrf]}, "/upload", "Back to uploads",
                eyebrow="Upload",
            ):
                return
            analysis = create_analysis(bundle, account_id=account.account_id)
        except PipelineFailure as error:
            logger.warning("analysis pipeline failed: %s", error)
            self._upload_error(422, [str(error)], title=title, account=account)
            return
        except UploadError as error:
            logger.info("upload rejected: %s", error)
            if error.status in (411, 413):
                self._send(
                    error.status,
                    _error_document(
                        "Upload not accepted",
                        str(error),
                        action_href="/upload",
                    ),
                )
            else:
                self._upload_error(
                    error.status, [str(error)], account=account
                )
            return

        location = "/?" + urllib.parse.urlencode({"analysis": analysis.analysis_id})
        self._send(HTTPStatus.SEE_OTHER, "", headers=[("Location", location)])

    def _upload_error(
        self,
        status: int,
        errors: list[str],
        *,
        title: str = "",
        account: Account | None = None,
    ) -> None:
        body = render_upload_page(
            analyses=list_analyses(
                account_id=account.account_id if account is not None else None
            ),
            errors=errors,
            title=title,
            account=account,
        )
        self._send(status, body)

    def _read_upload_body(self) -> bytes:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise UploadError(
                "The browser did not send a Content-Length header.", status=411
            )
        try:
            length = int(raw_length)
        except ValueError:
            raise UploadError("The upload length is not valid.") from None
        if length <= 0:
            raise UploadError("The upload was empty.")
        if length > MAX_REQUEST_BYTES:
            raise UploadError(
                "The upload is larger than the allowed limit.", status=413
            )
        body = self.rfile.read(length)
        if len(body) != length:
            raise UploadError("The upload ended before all bytes arrived.")
        return body

    def _same_origin(self) -> bool:
        site = self.headers.get("Sec-Fetch-Site", "").strip().lower()
        if site == "cross-site":
            return False
        host = self.headers.get("Host", "")
        if not host:
            return False
        origin = self.headers.get("Origin")
        if origin:
            parsed = urllib.parse.urlsplit(origin)
            return (
                parsed.scheme in {"http", "https"}
                and parsed.netloc.lower() == host.lower()
            )
        # Browsers send Origin on form POSTs. Sec-Fetch-Site is the fallback;
        # a state-changing request with neither header is refused.
        return site == "same-origin"

    def _requested_analysis(
        self, query: dict[str, list[str]], account: Account | None
    ) -> tuple[AnalysisWorkspace | None, str | None]:
        requested = _first(query, "analysis")
        if not requested:
            return None, None
        analysis = workspace_for(requested)
        if (
            analysis is None
            or account is None
            or analysis.account_id != account.account_id
        ):
            return None, (
                "That analysis is not available. It may have been removed, or it "
                "may belong to another account."
            )
        return analysis, None

    def _sample(self, path: str, *, head_only: bool) -> None:
        name = path.removeprefix("/samples/")
        source = SAMPLE_FILES.get(name)
        if source is None or not source.is_file():
            body = _error_document(
                "Sample not found",
                "That sample file is not part of this project.",
                action_href="/upload",
            )
            self._send(HTTPStatus.NOT_FOUND, body, head_only=head_only)
            return
        text = source.read_text(encoding="utf-8")
        self._send(
            HTTPStatus.OK,
            text,
            headers=[("Content-Disposition", f'attachment; filename="{name}"')],
            content_type="text/csv; charset=utf-8",
            head_only=head_only,
        )

    def _dispatch(self, *, head_only: bool) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        self._set_csrf_context()
        try:
            if path == "/healthz":
                self._health(head_only=head_only)
            elif path == "/":
                self._page(query, head_only=head_only)
            elif path == "/login":
                self._login_page(query, head_only=head_only)
            elif path == "/signup":
                self._signup_page(query, head_only=head_only)
            elif path == "/welcome":
                self._welcome_page(query, head_only=head_only)
            elif path == "/account":
                self._account_page(query, head_only=head_only)
            elif path == "/reset":
                self._reset_page(query, head_only=head_only)
            elif path == "/privacy":
                self._legal_page("Privacy notice", legal.privacy_body(), head_only=head_only)
            elif path == "/terms":
                self._legal_page("Terms of use", legal.terms_body(), head_only=head_only)
            elif path == "/delete-analysis":
                self._delete_analysis_page(query, head_only=head_only)
            elif path == "/upload":
                self._upload_page(query, head_only=head_only)
            elif path == "/plan":
                self._plan_page(query, head_only=head_only)
            elif path == "/export.csv":
                self._export(query, head_only=head_only)
            elif path == "/report":
                self._report(query, head_only=head_only)
            elif path.startswith("/samples/"):
                self._sample(path, head_only=head_only)
            elif path == "/assets/plan-it-logo.jpg":
                self._logo_asset(head_only=head_only)
            elif path == "/favicon.ico":
                self._no_content()
            else:
                body = _error_document(
                    "Page not found",
                    "That address is not part of the spending explorer. Use the dashboard "
                    "filters to choose a view.",
                )
                self._send(HTTPStatus.NOT_FOUND, body, head_only=head_only)
        except sqlite3.Error:
            logger.exception("warehouse query failed")
            body = _error_document(
                "The warehouse is unavailable",
                "The dashboard could not query the warehouse. Rerun "
                "'student-spending' to rebuild it, then reload this page.",
            )
            self._safe_send(HTTPStatus.SERVICE_UNAVAILABLE, body, head_only=head_only)
        except (BrokenPipeError, ConnectionResetError):
            logger.debug("client disconnected before the response finished")
        except Exception:  # noqa: BLE001 - one bad request must not stop the server
            logger.exception("unexpected dashboard failure")
            body = _error_document(
                "Something went wrong",
                "The dashboard hit an unexpected error. Check the server log, then try again.",
            )
            self._safe_send(HTTPStatus.INTERNAL_SERVER_ERROR, body, head_only=head_only)

    def _safe_send(self, status: int, body: str, *, head_only: bool) -> None:
        try:
            self._send(status, body, head_only=head_only)
        except (BrokenPipeError, ConnectionResetError):
            logger.debug("client disconnected before the error response finished")

    def _open(self, db_path: Path | None = None) -> sqlite3.Connection:
        return connect_readonly(db_path or self.server.db_path)

    def _page(self, query: dict[str, list[str]], *, head_only: bool) -> None:
        account = self._current_account()
        analysis, error = self._requested_analysis(query, account)
        if error:
            self._send(
                HTTPStatus.NOT_FOUND,
                _error_document("Analysis not found", error, action_href="/upload"),
                head_only=head_only,
            )
            return
        db_path = analysis.db_path if analysis else self.server.db_path
        report_path = analysis.report_path if analysis else self.server.report_path
        connection = self._open(db_path)
        try:
            body = render_dashboard(
                connection,
                query,
                report_available=report_path.is_file(),
                analysis=analysis,
                account=account,
            )
        finally:
            connection.close()
        self._send(HTTPStatus.OK, body, head_only=head_only)

    def _export(self, query: dict[str, list[str]], *, head_only: bool) -> None:
        analysis, error = self._requested_analysis(query, self._current_account())
        if error:
            self._send(
                HTTPStatus.NOT_FOUND,
                _error_document("Analysis not found", error, action_href="/upload"),
                head_only=head_only,
            )
            return
        db_path = analysis.db_path if analysis else self.server.db_path
        connection = self._open(db_path)
        try:
            filters, errors = parse_filters(query, load_options(connection))
            if errors:
                body = _error_document(
                    "Filters need attention",
                    " ".join(errors) + " Adjust the filters on the dashboard first.",
                    action_href="/" + _analysis_suffix(analysis),
                )
                self._send(HTTPStatus.BAD_REQUEST, body, head_only=head_only)
                return
            csv_text = render_csv(connection, filters)
        finally:
            connection.close()
        filename = (
            f"student-spending-{filters.date_from or 'all'}-to-{filters.date_to or 'all'}.csv"
        )
        self._send(
            HTTPStatus.OK,
            csv_text,
            headers=[("Content-Disposition", f'attachment; filename="{filename}"')],
            content_type="text/csv; charset=utf-8",
            head_only=head_only,
        )

    def _report(
        self, query: dict[str, list[str]], *, head_only: bool
    ) -> None:
        analysis, error = self._requested_analysis(query, self._current_account())
        if error:
            self._send(
                HTTPStatus.NOT_FOUND,
                _error_document("Analysis not found", error, action_href="/upload"),
                head_only=head_only,
            )
            return
        report_path = analysis.report_path if analysis else self.server.report_path
        if not report_path.is_file():
            body = _error_document(
                "No report yet",
                "Run 'student-spending' to build the static report, then reload this page.",
                action_href="/" + _analysis_suffix(analysis),
            )
            self._send(HTTPStatus.NOT_FOUND, body, head_only=head_only)
            return
        report_text = report_path.read_text(encoding="utf-8")
        self._send(HTTPStatus.OK, report_text, head_only=head_only)


def create_server(
    db_path: Path | str,
    *,
    host: str | None = None,
    port: int = 0,
    report_path: Path | str | None = None,
    accounts_path: Path | str | None = None,
    secure_cookies: bool | None = None,
) -> DashboardServer:
    db_path = Path(db_path)
    if not db_path.is_file():
        raise FileNotFoundError(f"warehouse not found: {db_path}")
    if report_path is None:
        report_path = config.REPORTS_DIR / "spending_report.html"
    if secure_cookies is None:
        secure_cookies = config.SECURE_COOKIES
    return DashboardServer(
        (host or config.HOST, port),
        db_path=db_path,
        report_path=Path(report_path),
        accounts_path=accounts_path,
        secure_cookies=secure_cookies,
    )


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(config.PROJECT_ROOT))
    except ValueError:
        return str(path)


def serve(
    db_path: Path | str = config.DEFAULT_DB_PATH,
    *,
    host: str | None = None,
    port: int = 8000,
    open_browser: bool = False,
    accounts_path: Path | str | None = None,
    secure_cookies: bool | None = None,
) -> int:
    """Start the dashboard and block until Ctrl+C. Returns a process exit code."""
    problems = config.production_problems()
    if problems:
        print("Refusing to start: production configuration is incomplete.")
        for problem in problems:
            print(f"  - {problem}")
        print("Set the missing PLANIT_* variables, then start the service again.")
        return 2
    host = host or config.HOST
    secure_cookies = config.SECURE_COOKIES if secure_cookies is None else secure_cookies
    db_path = Path(db_path)
    if not db_path.is_file():
        print(f"Warehouse not found: {db_path}")
        print("Build it first with: student-spending --full-refresh")
        return 2
    try:
        connection = connect_readonly(db_path)
        try:
            row_count = connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        finally:
            connection.close()
    except sqlite3.Error as error:
        print(f"Could not read the warehouse at {db_path}: {error}")
        print("Rebuild it with: student-spending --full-refresh")
        return 2
    if not row_count:
        print(f"The warehouse at {db_path} has no transactions.")
        print("Build it first with: student-spending --full-refresh")
        return 2

    try:
        server = create_server(
            db_path,
            host=host,
            port=port,
            accounts_path=accounts_path,
            secure_cookies=secure_cookies,
        )
    except OSError as error:
        print(f"Could not start the dashboard on {host}:{port}: {error}")
        print("Try another port, for example: student-spending serve --port 8001")
        return 2

    bound_host, bound_port = server.server_address[:2]
    display_host = "127.0.0.1" if bound_host in ("0.0.0.0", "::") else str(bound_host)
    if ":" in display_host:
        display_host = f"[{display_host}]"
    scheme = "https" if secure_cookies else "http"
    url = config.PUBLIC_URL or f"{scheme}://{display_host}:{bound_port}/"
    if not url.endswith("/"):
        url += "/"
    print()
    print("Student Spending Explorer")
    print(f"  {url}")
    print(f"  warehouse: {_display_path(db_path)} (read-only)")
    print(f"  accounts: {_display_path(server.accounts.path)} (private)")
    if config.PRODUCTION:
        print(f"  environment: production ({config.PUBLIC_URL})")
        print("  personal data: keep disks and backups encrypted; review the runbook")
    else:
        print("  environment: development; local accounts, data stays on this machine")
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"  listening on {host}:{bound_port}")
        print("  put TLS and request limits in front; do not expose this port directly")
    if secure_cookies:
        print("  secure cookies: on (the browser must reach the service over HTTPS)")
    print()

    if open_browser:
        threading.Timer(0.6, webbrowser.open, args=(url,)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Dashboard stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
