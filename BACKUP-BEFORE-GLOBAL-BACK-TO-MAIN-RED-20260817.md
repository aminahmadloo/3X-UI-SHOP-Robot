# Backup point before global back-to-main red button fix

Successful baseline: `4aac4880dedd6e22b149eea72910892db345d900`

Issue: some buttons labeled "بازگشت به منوی اصلی" were created directly instead of using `back_to_main_menu_button()`, so they did not receive the red `danger` style.

Change planned: replace direct back-to-main button construction with the shared helper so every button with this action uses the red style consistently.

Do not mark the next commit successful until it is deployed and tested on the running bot.
