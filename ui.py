"""Reusable UI components."""
import streamlit as st

def inject_tailwind():
    st.markdown("""<link href="https://cdn.jsdelivr.net/npm/tailwindcss@3.4.5/dist/tailwind.min.css" rel="stylesheet">
<style>
html,body,[class*="css"]{font-family:'Inter',ui-sans-serif,system-ui,sans-serif}
.tw-card{border:1px solid #E5E7EB;border-radius:12px;padding:18px 20px;background:#FFF;box-shadow:0 1px 2px rgba(0,0,0,.03)}
.tw-card-title{font-size:13px;color:#6B7280;text-transform:uppercase;letter-spacing:.04em;font-weight:600;margin-bottom:6px}
.tw-card-value{font-size:26px;font-weight:700;line-height:1.1}.tw-card-sub{font-size:12px;color:#6B7280;margin-top:4px}
.tw-hero{background:linear-gradient(135deg,#0F766E 0%,#14B8A6 100%);color:#FFF;padding:28px 32px;border-radius:16px;margin-bottom:24px}
.tw-hero h1{font-size:28px;font-weight:700;margin:0 0 4px}.tw-hero p{font-size:14px;opacity:.92;margin:0}
.tw-upload{border:2px dashed #CBD5E1;border-radius:14px;padding:22px;background:#F8FAFC;text-align:center}
.tw-upload-title{font-weight:700;color:#0F172A;font-size:15px}.tw-upload-sub{color:#64748B;font-size:12px;margin-bottom:8px}
[data-testid="stFileUploader"] section{background:transparent!important;border:none!important;padding:0!important}
.tw-section-title{font-size:18px;font-weight:700;color:#0F172A;margin:26px 0 10px}.tw-section-sub{font-size:13px;color:#64748B;margin-bottom:12px}
.tw-kv{font-size:13px;color:#374151}
</style>""",unsafe_allow_html=True)

def hero(title,subtitle):
    st.markdown(f'<div class="tw-hero"><h1>{title}</h1><p>{subtitle}</p></div>',unsafe_allow_html=True)
def section(title,subtitle=""):
    sub=f'<div class="tw-section-sub">{subtitle}</div>' if subtitle else ""
    st.markdown(f'<div class="tw-section-title">{title}</div>{sub}',unsafe_allow_html=True)
def upload_card(title,subtitle):
    st.markdown(f'<div class="tw-upload"><div class="tw-upload-title">{title}</div><div class="tw-upload-sub">{subtitle}</div></div>',unsafe_allow_html=True)
def metric_card(label,value,sub="",tone="neutral"):
    colors={"neutral":"#111827","good":"#166534","warn":"#92400E","bad":"#991B1B","info":"#1E40AF"}
    st.markdown(f'<div class="tw-card"><div class="tw-card-title">{label}</div><div class="tw-card-value" style="color:{colors.get(tone,"#111827")}">{value}</div><div class="tw-card-sub">{sub}</div></div>',unsafe_allow_html=True)
