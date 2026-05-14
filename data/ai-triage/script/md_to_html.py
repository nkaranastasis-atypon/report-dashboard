#!/usr/bin/env python3
"""
md_to_html.py — Convert a Jira triage markdown report to a styled HTML file.

Usage:
    python md_to_html.py <input.md> <output.html>
"""

import sys
import os
import re
from datetime import datetime

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      font-size: 14px;
      line-height: 1.6;
      color: #172B4D;
      max-width: 900px;
      margin: 40px auto;
      padding: 0 24px;
      background: #F4F5F7;
    }}
    .card {{
      background: #fff;
      border-radius: 4px;
      box-shadow: 0 1px 3px rgba(9,30,66,.13);
      padding: 32px 40px;
    }}
    h1 {{ font-size: 20px; font-weight: 600; color: #172B4D;
          border-bottom: 2px solid #DFE1E6; padding-bottom: 12px; margin-top: 0; }}
    h2 {{ font-size: 15px; font-weight: 600; color: #172B4D;
          margin-top: 28px; margin-bottom: 6px; }}
    h3 {{ font-size: 13px; font-weight: 600; color: #5E6C84;
          margin-top: 20px; margin-bottom: 4px; }}
    p {{ margin: 6px 0; }}
    code {{
      background: #F4F5F7; border: 1px solid #DFE1E6; border-radius: 3px;
      padding: 2px 5px;
      font-family: 'SFMono-Regular', Consolas, monospace; font-size: 12px;
    }}
    pre {{
      background: #F4F5F7; border: 1px solid #DFE1E6; border-radius: 3px;
      padding: 12px 16px; overflow-x: auto;
      font-family: 'SFMono-Regular', Consolas, monospace; font-size: 12px;
    }}
    pre code {{ background: none; border: none; padding: 0; }}
    blockquote {{
      border-left: 3px solid #DFE1E6; padding-left: 16px;
      color: #5E6C84; margin: 12px 0; font-style: italic;
    }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
    th, td {{ border: 1px solid #DFE1E6; padding: 8px 12px; text-align: left; }}
    th {{ background: #F4F5F7; font-weight: 600; }}
    a {{ color: #0052CC; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    hr {{ border: none; border-top: 1px solid #DFE1E6; margin: 24px 0; }}
    .generated {{ font-size: 11px; color: #97A0AF; margin-top: 32px; text-align: right; }}
  </style>
</head>
<body>
  <div class="card">
    {body}
    <p class="generated">Generated {timestamp}</p>
  </div>
</body>
</html>"""


def escape_html(text):
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def inline_format(text):
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    return text


def md_to_html_body(md_text):
    lines = md_text.splitlines()
    html_lines = []
    in_pre = False

    for line in lines:
        if line.strip().startswith("```"):
            if not in_pre:
                lang = line.strip()[3:].strip()
                html_lines.append(f'<pre><code class="language-{lang}">')
                in_pre = True
            else:
                html_lines.append('</code></pre>')
                in_pre = False
            continue
        if in_pre:
            html_lines.append(escape_html(line))
            continue
        h_match = re.match(r'^(#{1,6})\s+(.*)', line)
        if h_match:
            level = len(h_match.group(1))
            html_lines.append(f'<h{level}>{inline_format(h_match.group(2))}</h{level}>')
            continue
        if re.match(r'^---+$', line.strip()):
            html_lines.append('<hr>')
            continue
        if line.startswith('> '):
            html_lines.append(f'<blockquote><p>{inline_format(line[2:])}</p></blockquote>')
            continue
        li_match = re.match(r'^\s*[-*]\s+(.*)', line)
        if li_match:
            html_lines.append(f'<li>{inline_format(li_match.group(1))}</li>')
            continue
        ol_match = re.match(r'^\s*\d+\.\s+(.*)', line)
        if ol_match:
            html_lines.append(f'<li>{inline_format(ol_match.group(1))}</li>')
            continue
        if not line.strip():
            html_lines.append('')
            continue
        html_lines.append(f'<p>{inline_format(line)}</p>')

    return '\n'.join(html_lines)


def extract_title(md_text):
    for line in md_text.splitlines():
        h1 = re.match(r'^#\s+(.*)', line)
        if h1:
            return h1.group(1)
    return "Triage Report"


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.md> <output.html>")
        sys.exit(1)

    input_path, output_path = sys.argv[1], sys.argv[2]
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    with open(input_path, 'r', encoding='utf-8') as f:
        md_text = f.read()

    title = extract_title(md_text)
    body = md_to_html_body(md_text)
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    html = HTML_TEMPLATE.format(title=escape_html(title), body=body, timestamp=timestamp)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"HTML report written to: {output_path}")

if __name__ == "__main__":
    main()
