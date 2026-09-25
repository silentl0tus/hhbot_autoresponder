import re

with open("app/parsers/hh_playwright.py", "r") as f:
    content = f.read()

# 1. Update _fill_response_form to skip callable cover_letter
# Look for:
#         if cover_letter:
#             if callable(cover_letter):
#                 log.info("hh_cover_letter_generating_deferred")
old_fill = """        if cover_letter:
            if callable(cover_letter):
                log.info("hh_cover_letter_generating_deferred")
                try:
                    import asyncio
                    cover_letter = await cover_letter() if asyncio.iscoroutinefunction(cover_letter) else cover_letter()
                except Exception as e:
                    log.error("hh_deferred_cover_letter_error", error=str(e))
                    cover_letter = ""

        if cover_letter:
            filled = False
            for attempt in (1, 2, 3):"""
new_fill = """        if cover_letter:
            if callable(cover_letter):
                # Пропускаем заполнение на этом этапе, чтобы не тратить токены.
                # Письмо будет прикреплено после успешного отклика.
                log.info("hh_skipping_cover_letter_in_form_to_save_tokens")
                return
            
            filled = False
            for attempt in (1, 2, 3):"""
content = content.replace(old_fill, new_fill)

with open("app/parsers/hh_playwright.py", "w") as f:
    f.write(content)

