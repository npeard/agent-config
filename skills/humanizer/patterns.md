<!-- check-ascii: allow - patterns 14 and 19 name the characters themselves -->

# Humanizer pattern catalog

The 35 patterns behind the `humanizer` skill. Read this before
rewriting: the skill file carries the process, this file carries what to
look for.

Worked before/after rewrites live in `examples.md`, keyed by the same
numbers. Open an entry there for a pattern you are actually rewriting;
you do not need it to find one.

## Content patterns

### 1. Inflated claims about importance and legacy

**Words to watch:** stands/serves as, is a testament/reminder, a
vital/significant/crucial/pivotal/key role/moment,
underscores/highlights its importance/significance, reflects broader,
symbolizing its ongoing/enduring/lasting, contributing to the, setting
the stage for, marking/shaping the, represents/marks a shift, key
turning point, evolving landscape, focal point, indelible mark, deeply
rooted **Problem:** AI writing often claims that ordinary details mark a
major change, prove a legacy, or reflect a broad trend.

### 2. Name-dropping to prove importance

**Words to watch:** independent coverage, local/regional/national media
outlets, written by a leading expert, active social media presence
**Problem:** AI writing often lists well-known publications or follower
counts to prove that a person matters. The list usually gives no useful
context.

If the source explains what the person said and where, keep that useful
citation. Do not invent context for a shorter version.

### 3. Shallow analysis with -ing phrases

**Words to watch:** highlighting/underscoring/emphasizing...,
ensuring..., reflecting/symbolizing..., contributing to...,
cultivating/fostering..., encompassing..., showcasing... **Problem:** AI
writing often adds an -ing phrase to make a simple fact sound deeper
than it is.

### 4. Sales language

**Words to watch:** boasts a, vibrant, rich (figurative), profound,
enhancing its, showcasing, exemplifies, commitment to, natural beauty,
nestled, in the heart of, groundbreaking (figurative), renowned,
breathtaking, must-visit, stunning **Problem:** AI writing often sounds
like an advertisement, especially when it describes places, culture,
products, or organizations.

### 5. Vague sources

**Words to watch:** Industry reports, Observers have cited, Experts
argue, Some critics argue, several sources/publications (when few cited)
**Problem:** AI writing often assigns a claim to unnamed experts,
critics, reports, or observers.

Name a real source when the source text provides one. Otherwise, remove
the unsupported claim. Never invent a source.

### 6. Formulaic challenges and outlook sections

**Words to watch:** Despite its... faces several challenges..., Despite
these challenges, Challenges and Legacy, Future Outlook **Problem:** AI
articles often add a stock section about challenges, future prospects,
or continued growth. These sections usually repeat vague claims instead
of adding facts.

Add details such as dates or public actions only when they come from the
source or the user.

## Language and grammar patterns

### 7. Overused AI words

**High-frequency AI words:** Actually, additionally, align with,
crucial, delve, emphasizing, enduring, enhance, fostering, garner,
gate/gated/gating (figurative; preserve established technical usage),
highlight (verb), interplay, intricate/intricacies, key (adjective),
landscape (abstract noun), pivotal, quietly, showcase, tapestry
(abstract noun), testament, underscore (verb), valuable, vibrant
**Problem:** AI writing uses these words much more often than most
people do, especially in groups.

### 8. Avoiding is and are

**Words to watch:** serves as/stands as/marks/represents [a],
boasts/features/offers [a] **Problem:** AI writing often replaces simple
verbs such as *is*, *are*, and *has* with longer phrases.

### 9. Not X but Y and clipped negative endings

**Problem:** AI writing overuses forms such as "Not only...but..." and
"It's not just X, it's Y."

It also adds clipped endings such as "no guessing" instead of writing a
clear clause.

### 10. Forced groups of three

**Problem:** AI writing often forces ideas into groups of three to sound
complete.

### 11. Changing names and repeating sentence openings

**Problem:** AI writing handles repetition by rule instead of by ear. It
may keep renaming the same person or thing. It may also start several
sentences with the same subject, often *she* or *he*.

Use one clear name for the same subject. For repeated openings, merge
sentences, change the subject when that helps, or begin with the action.

Do not ban the repeated word. Fix the repeated sentence pattern. The
remaining sentence may still start with "She."

### 12. False from X to Y ranges

**Problem:** AI writing often uses "from X to Y" when X and Y do not
form a real range.

### 13. Passive voice and missing subjects

**Problem:** AI writing often hides who acts or drops the subject. Use
active voice when it makes the actor and action clearer.

## Style patterns

### 14. Em and en dashes

**Rule:** The final rewrite must not contain em dashes (—) or en dashes
(–), unless the writer's sample uses them. Replace a dash with a period,
comma, colon, or parentheses, or rewrite the sentence. Also check for
spaced dashes (`—`) and double hyphens (`--`) used as dashes.

Before returning the rewrite, search for `—` and `–`. Remove each one
unless the writer's sample uses that mark. In that case, match the
sample's rate.

### 15. Too much bold text

**Problem:** AI chatbots often bold words and phrases without a clear
reason.

### 16. Lists with bold mini-headings

**Problem:** AI writing often uses vertical lists in which every item
starts with a bold label and a colon.

### 17. Title case in headings

**Problem:** AI chatbots often capitalize every main word in a heading.

### 18. Emojis

**Problem:** AI chatbots often add emojis to headings and list items as
decoration.

### 19. Curly quotation marks

**Problem:** ChatGPT often uses curly quotes (“...”) where the writer or
target format uses straight quotes ("...").

## Chatbot patterns

### 20. Chatbot text left in the answer

**Words to watch:** I hope this helps, Of course!, Certainly!, You're
absolutely right!, Would you like..., Want me to...?, Want me to give
examples?, Should I continue?, let me know, here is a... **Problem:** A
chatbot's greeting, offer, or closing sometimes remains in text that
should stand on its own.

### 21. Knowledge-limit disclaimers and guesses

**Words to watch:** as of [date], Up to my last training update, While
specific details are limited/scarce..., based on available information,
not publicly available, maintains a low profile, keeps personal details
private, prefers to stay out of the spotlight, likely \[grew
up/studied/began\], it is believed that **Problem:** Older models may
mention the date when their knowledge ends. A model may also explain
that it could not find a source, then fill the gap with a plausible
guess. State what the source does not show, or remove the sentence. Do
not present a guess as a fact.

### 22. Overly agreeable tone

**Problem:** AI assistants often praise the user or agree before giving
the answer.

## Filler and hedging

### 23. Filler phrases

**Before -> After:**

- "In order to achieve this goal" -> "To achieve this"
- "Due to the fact that it was raining" -> "Because it was raining"
- "At this point in time" -> "Now"
- "In the event that you need help" -> "If you need help"
- "The system has the ability to process" -> "The system can process"
- "It is important to note that the data shows" -> "The data shows"

### 24. Too many qualifiers

**Phrases to watch:** to be fair, it's also possible, could potentially,
might arguably, in some cases it may, this is an inference **Problem:**
Repeated editing can add one qualifier after another until every claim
sounds uncertain. Keep a qualifier only when the source supports it and
the meaning needs it. Remove caveats that only repair an earlier
overstatement.

### 25. Generic positive endings

**Problem:** AI writing often ends with vague optimism instead of the
last useful fact.

### 26. Too many hyphenated word pairs

**Words to watch:** third-party, cross-functional, client-facing,
data-driven, decision-making, well-known, high-quality, real-time,
long-term, end-to-end **Problem:** AI writing often hyphenates these
pairs everywhere. Keep the hyphen before a noun when grammar needs it,
as in `a high-quality report`. Drop it after the noun, as in
`the report is high quality`.

### 27. Pretending to reveal a deeper truth

**Phrases to watch:** The real question is, at its core, in reality,
what really matters, fundamentally, the deeper issue, the heart of the
matter **Problem:** AI writing uses these phrases to make an ordinary
point sound like a hidden truth.

### 28. Announcing the next point

**Phrases to watch:** Let's dive in, let's explore, let's break this
down, here's what you need to know, now let's look at, without further
ado, heads up, quick note, before I forget **Problem:** AI writing often
announces the next point instead of stating it. A casual phrase such as
"one thing that bit me" can have the same problem. Remove the
announcement, not just its formal tone.

### 29. A heading repeated in the first sentence

**Signs to watch:** A heading followed by a one-line paragraph that
simply restates the heading before the real content begins. **Problem:**
AI writing often follows a heading with a sentence that only repeats the
heading. Remove the repeated sentence.

### 30. Writing about the previous version

**Problem:** Documentation and comments should describe the current
behavior. Mention the previous version only in change logs, release
notes, migration guides, and other documents about change.

### 31. Forced punchlines and dramatic fragments

**Problem:** AI writing often turns each sentence into a dramatic
closing line. One short sentence can add emphasis. A row of short
fragments usually feels forced.

### 32. Formulaic sayings

**Words to watch:** X is the Y of Z, X becomes a trap, X is not a tool
but a mirror, the language of, the currency of, the architecture of
**Problem:** AI writing often turns an ordinary claim into a saying that
sounds deep but adds no detail. Replace the saying with the specific
claim.

### 33. Fake-candid openings

**Phrases to watch:** Honestly?, Look, Here's the thing, The thing is,
Let's be honest, Real talk, when used as standalone hooks or fake-candid
pauses before an ordinary point. **Problem:** AI writing often starts
with a staged pause or claim of honesty before making a routine point.
State the point directly.

### 34. Answering objections no one raised

**Phrases to watch:** This isn't (mainly/really) about, I'm not
saying/arguing/trying to, To be clear, Don't get me wrong, This is not
to say, You could argue/frame this differently but, Some might say...
but **Problem:** AI writing may answer an objection that does not appear
in the text. Watch for an unattributed statement about what the writer
does not mean, especially when the topic appears nowhere else. A direct
claim such as "the API is not thread-safe" is not this pattern.

Remove only the unsupported defense. If it contains a real claim, state
that claim directly. Keep an objection when the text names its source or
answers it in full.

### 35. Rejecting fake alternatives

**Phrases to watch:** A tempting option/approach would be, One might be
tempted to, An obvious approach would be, You might think... but, It
would be easy to just, Some would suggest **Problem:** AI writing may
introduce an option that no reader would consider, reject it in a
clause, and never mention it again. This often leaves an old drafting
idea in the final text. Remove the fake option and state the real
constraint directly.

One rejected option may be valid. Several short, unrelated rejections
are a stronger sign. Ask what new information each sentence adds. If it
only records an earlier edit, rewrite the paragraph around its main
point.
