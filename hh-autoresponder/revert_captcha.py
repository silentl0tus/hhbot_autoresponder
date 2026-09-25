import subprocess
import re

# Get old file content
old_content = subprocess.check_output(["git", "show", "HEAD~1:hh-autoresponder/app/parsers/hh_playwright.py"]).decode(
    "utf-8"
)

old_func_start = "    async def _request_manual_captcha(self, page) -> bool:"
old_func_end = "    def resolve_captcha(self, text: str):"

match_old = re.search(
    re.escape(old_func_start) + r"(.*?)" + re.escape("    def resolve_captcha(self, text: str):"),
    old_content,
    re.DOTALL,
)
if not match_old:
    print("Could not find old func")
    exit(1)

old_block = old_func_start + match_old.group(1)

# Now read current file
with open("app/parsers/hh_playwright.py", "r") as f:
    current_content = f.read()

match_current = re.search(
    re.escape(old_func_start) + r"(.*?)" + re.escape("    def resolve_captcha(self, text: str):"),
    current_content,
    re.DOTALL,
)
if not match_current:
    print("Could not find current func")
    exit(1)

current_block = old_func_start + match_current.group(1)

new_content = current_content.replace(current_block, old_block)

with open("app/parsers/hh_playwright.py", "w") as f:
    f.write(new_content)

print("Done restoring old captcha logic.")
