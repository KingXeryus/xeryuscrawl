# XeryusCrawl terms of use and sharing

By installing or using XeryusCrawl you agree to its licence ([LICENSE.md](LICENSE.md), PolyForm Noncommercial 1.0.0) and to
these terms. Français : [TERMS.fr.md](TERMS.fr.md).

## 1. Using XeryusCrawl

- You use XeryusCrawl on your own computer and are responsible for what you read, crawl and keep with it, including
  respecting websites' terms, copyright and the law where you are. It follows robots.txt and keeps a polite pace by default.
- Stealth mode (off unless you turn it on) must not be used to get around logins, paywalls or a website's explicit refusal.
- XeryusCrawl is provided as is, without warranty, to the extent the law allows.
- When you use a cloud AI provider or Brave Search, your requests go to that provider under its own terms, with your own key.

## 2. Sharing research passages (only if you say yes)

**Sharing is off unless you turn it on.** `xeryuscrawl setup` asks you once; you can change your answer any time with
`xeryuscrawl sharing on` or `xeryuscrawl sharing off`. Nothing is shared before you say yes, and turning it off deletes
anything still waiting to be sent.

**Who receives it.** myMAK.ai, Oakville, Ontario, Canada (the controller). Contact our Privacy Officer at
support@mymak.ai.

**What is shared.** When you run deep research, the public web passages it finds: the text of each passage, its web address
and page title. Before anything is kept, email addresses, phone numbers, long numbers and things that look like keys are
blanked. Only passages from a list of trusted public sources (such as Wikipedia, encyclopedias, science journals and
government and university sites) are accepted; others are refused and not kept. A random install id is sent with them;
myMAK.ai stores only a one-way hash of it.

**What is never shared.** Your questions, searches and answers, your API keys, your files, the pages you scrape outside deep
research, and anything else on your computer. myMAK.ai doesn't store your IP address. To apply a daily limit on sharing, it
keeps a protected one-way code made from your IP address with a secret key (a keyed hash), which can't be turned back into
the address. It is deleted with the passages, within 30 days.

**Why.** To train and improve AI models made by myMAK.ai, which may be used in its products, including paid ones. The legal
basis is your consent, which you can withdraw at any time.

**How it's handled.** Passages are sent at most once a day over an encrypted connection to myMAK.ai's database (Supabase).
myMAK.ai collects them weekly, checks each one against its source page, removes duplicates and private details again, and
deletes them from that database; anything not collected is deleted after 30 days. Once a passage has been used to train a
model it can't be removed from that model, but it's public web text, not information about you.

**Your rights.** Depending on where you live (including Quebec, the rest of Canada, the EU and UK, and California) you can
ask to access, correct or delete information about you, or complain to your data protection authority. Because what you
share is public web text linked only to a random id, send your install id (in `~/.xeryuscrawl/config.json`) with any request
to support@mymak.ai.

## 3. Changes

If these terms change, the new version is published here with its date. A change to what is shared or why will ask you
again before it applies.

Version 2, 2026-11-09: trusted sources only; a protected one-way code of the IP address kept for the daily limit.
