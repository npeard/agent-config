---
name: humanizer
description: |-
  Use when editing or reviewing prose for inflated claims, sales language,
  vague sources, repetitive structure, stock AI words, passive voice, filler,
  or chatbot artifacts -- rewrites AI-sounding text so it reads naturally
  without changing what it says. Based on Wikipedia's "Signs of AI writing."
---

# Humanizer: remove AI writing patterns

Rewrite AI-sounding text so it reads like the writer, not a chatbot. Do
not change what it says or make up details.

The patterns below come from Wikipedia's
["Signs of AI writing"](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing),
maintained by WikiProject AI Cleanup.

## What to do

When given text to humanize:

1. **Find AI patterns.** Read `patterns.md` in this skill directory and
   check the text against all 35 patterns. That file carries what to
   look for; the worked before/after rewrites sit in `examples.md` under
   the same numbers. Open an entry there for a pattern you are actually
   rewriting, not to find one.
2. **Keep every claim.** You may shorten dull parts, expand useful
   parts, and merge or split paragraphs. Keep the information even when
   you change the structure.
3. **Do not invent facts.** Do not add a fact, name, number, date,
   quote, or citation unless it comes from the source or the user. If a
   sentence needs a missing detail, ask for it or use a simpler
   sentence. You may add an opinion or reaction when the writer's voice
   calls for one, but you may not add a factual claim. Fiction is exempt
   because invented details are part of the task.
4. **Match the voice.** Use the right tone for the text, such as formal,
   casual, or technical. Add personality only when the text and the
   writer call for it.

The input type controls what you return. See
[How to return the result](#how-to-return-the-result). Use the same
rewrite process in every mode.

## Match the writer's voice

If the user provides a writing sample (their own previous writing),
analyze it before rewriting:

1. Read the sample first. Note its sentence length, word choice,
   paragraph openings, punctuation, repeated phrases, and transitions.
2. Match those habits. Do not replace casual words with formal ones or
   remove deliberate quirks.
3. If there is no sample, use the guidance below.

A writing sample takes priority over these style rules. If the sample
uses em dashes, keep them at about the same rate. Do not apply pattern
14 as a ban.

## Add personality only when it fits

Removing AI patterns is only half the job. The result should still sound
like a person.

Use personality in blog posts, essays, opinions, and personal writing
when it fits the writer. Keep reference, technical, legal, and factual
text neutral. Do not add opinions or first-person language where they do
not belong.

When personality fits, keep the writer's opinions, uncertainty, mixed
feelings, humor, asides, and uneven rhythm. Never invent facts to make
the text feel personal.

## Check for false positives

### What not to flag

A person may use some of these patterns. Do not treat any item below as
proof by itself:

- **Perfect grammar and consistent style.** Many writers are
  professionals or have been edited. Polish does not equal AI.
- **Mixed casual and formal styles.** This can reflect the writer's
  field, age, or personal habits.
- **"Bland" or "robotic" prose.** AI prose has *specific* tells. Generic
  dryness without those tells is just dry writing.
- **Formal or academic words.** Pattern 7 lists specific words that AI
  writing overuses. Do not simplify every formal word.
- **Letter-style opening or closing on a comment.** Salutations and
  sign-offs predate ChatGPT by centuries.
- **Common transition words in isolation.** *Additionally*, *moreover*,
  *consequently* are AI-coded only when piled up. One *however* is not a
  tell.
- **Curly quotes alone.** macOS, Word, Google Docs, and most CMSes
  auto-curl by default. Curly quotes only count when stacked with other
  tells.
- **Em dashes alone.** Many editors and journalists use them often. Em
  dashes are evidence only when paired with formulaic sales-y rhythm.
- **One short sentence for emphasis.** Flag dramatic fragments only when
  several appear in a row.
- **Deliberate repeated openings.** Writers may repeat an opening to
  build rhythm or pressure, as in "She came. She saw. She conquered."
  Change it only when the repetition adds nothing.
- **"Honestly" or "look" mid-sentence.** These are ordinary in casual
  writing. The tell is the standalone theatrical opener, not the word
  itself.
- **Useful limits and disclaimers.** Keep scope statements, legal and
  safety notices, real corrections, named objections, replies, and FAQ
  answers.
- **Real alternatives.** Keep options that a reader may consider in a
  design document, tutorial, or argument. Remove only an unlikely option
  that the text dismisses and never uses again.
- **Unsourced claims.** Most of the web is unsourced. Lack of citations
  doesn't prove anything.
- **Correct, complex formatting.** Visual editors and templates produce
  clean output without any AI.
- **Secondhand text.** Do not rewrite watched phrases inside quotations,
  titles, proper names, or examples where the phrase is being discussed
  rather than used.

When unsure, look for several patterns together. One em dash proves
nothing. Several stock patterns in the same passage are stronger
evidence.

### Human details to keep

These details often carry the writer's voice. Keep them unless they hurt
the meaning:

- **Specific, unusual details.** Keep a real address, an odd quote, or a
  phrase such as "the lawyer who used to work upstairs from my dentist."
- **Mixed feelings and unresolved tension.** Keep lines such as "I think
  this is mostly good, but it bothers me, and I can't fully explain
  why."
- **Dated, era-bound references.** Slang, memes, or in-jokes that map to
  a specific year and subculture. Models lag by a year or more.
- **Deliberate first-person choices.** Keep a cut or word choice when
  the writer can explain why it belongs.
- **Variety in sentence length.** Real writing alternates short and
  long. AI writing tends toward an even, mid-length cadence.
- **Genuine asides, parentheticals, or self-corrections.** "(I keep
  wanting to say 'almost' here, but it really was certain.)" Models
  rarely interrupt themselves like this.
- **Edits made before November 30, 2022.** ChatGPT's public launch.
  Anything older than that is, with very rare exceptions, not
  AI-written.

______________________________________________________________________

## How to return the result

**Pasted text (default).** Return the draft, a short list of remaining
AI patterns, and the final rewrite.

**File mode.** When the user names a file, run the full rewrite process
but write only the final text to the file. Change prose only. Keep code
blocks, YAML metadata, data, and link targets unchanged. Then give the
user a short summary.

**Embedded mode.** When another task uses this skill for a pull request,
commit message, or document, return only the final text.

## Rewrite process

1. Read the source and mark each AI pattern.
2. Write a draft. Read it aloud. Check the rhythm, details, simple verbs
   such as *is* and *has*, and the right level of formality.
3. Ask two questions:
   - **"What still sounds AI-generated?"**
   - **"Did the rewrite add or remove any fact, name, number, date,
     quote, citation, ranking, or other claim?"** Treat any unsupported
     addition or lost claim as an error.
4. Write the final version. State each point naturally instead of
   patching one flagged phrase at a time. If a sentence stays awkward,
   rewrite the paragraph around its main point. Apply the dash rule in
   pattern 14.

Return the result required by
[How to return the result](#how-to-return-the-result).

## Source

This skill is based on
[Wikipedia: Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing),
maintained by WikiProject AI Cleanup. Its patterns come from reviews of
AI-generated text on Wikipedia.

Wikipedia's main point: "LLMs use statistical algorithms to guess what
should come next. The result tends toward the most statistically likely
result that applies to the widest variety of cases."
