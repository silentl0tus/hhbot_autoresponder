import re

with open('app/parsers/hh_playwright.py', 'r', encoding='utf-8') as f:
    code = f.read()

# We need to replace:
#        for tab_name, url in tabs:
#            try:
#                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
#
# with:
#        for tab_name, base_url in tabs:
#            for page_num in range(15):
#                url = base_url + ("&" if "?" in base_url else "?") + f"page={page_num}"
#                try:
#                    await page.goto(url, wait_until="domcontentloaded", timeout=45000)

new_code = code.replace(
'''        for tab_name, url in tabs:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)''',
'''        for tab_name, base_url in tabs:
            for page_num in range(10):  # Fetch up to 10 pages per tab
                url = base_url + ("&" if "?" in base_url else "?") + f"page={page_num}"
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=45000)'''
)

# And we need to add the break logic:
#                if isinstance(items_data, dict):
#                    if items_data.get("sample_html"):
#                        log.info("hh_neg_sample_html", tab=tab_name, html=items_data["sample_html"][:800])
#                    items_data = items_data.get("items", [])
#
# -> add:
#                if not items_data:
#                    break

new_code = new_code.replace(
'''                if isinstance(items_data, dict):
                    if items_data.get("sample_html"):
                        log.info("hh_neg_sample_html", tab=tab_name, html=items_data["sample_html"][:800])
                    items_data = items_data.get("items", [])''',
'''                if isinstance(items_data, dict):
                    if items_data.get("sample_html") and page_num == 0:
                        log.info("hh_neg_sample_html", tab=tab_name, html=items_data["sample_html"][:800])
                    items_data = items_data.get("items", [])
                
                if not items_data:
                    break'''
)

# Fix indentation for the rest of the loop!
# Wait, replacing indentation using Python is easier:
# Actually, the entire `try: ... except Exception as e: log.warning(...)` block is inside `for tab_name, url in tabs:`.
# We need to indent everything inside `for tab_name, base_url in tabs:` by 4 spaces.
# Let's do it manually with sed or just run a script that modifies it line by line.

lines = new_code.split('\n')
start_idx = -1
end_idx = -1
for i, line in enumerate(lines):
    if 'for page_num in range(10):' in line:
        start_idx = i + 1
    elif start_idx != -1 and line == '        log.info("hh_negotiations_status", total=len(statuses),':
        end_idx = i
        break

if start_idx != -1 and end_idx != -1:
    for i in range(start_idx, end_idx):
        if lines[i].startswith('            '):
            if i > start_idx + 2: # Skip url=... and try:
                # We need to indent everything that was inside `for tab_name...` by 4 spaces
                lines[i] = '    ' + lines[i]

    with open('app/parsers/hh_playwright.py', 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print("Fixed!")
else:
    print("Could not find blocks.")

