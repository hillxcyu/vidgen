# Google Workspace Skill — Agent E2E Test Plan

## Prerequisites

**Read `SKILL.md` first** to understand available tools and when to use each.

--------------------------------------------------------------------------------

## Test 1: Find my recent Google Docs

**Prompt:** "Can you find some of my recent Google Docs?"

**Verify:**

-   Agent uses `gdrive` CLI to search for docs
-   Output shows document names and IDs
-   At least one result is returned

--------------------------------------------------------------------------------

## Test 2: Read a Google Doc

**Prompt:** "Read one of those Google Docs and show me its content."

**Verify:**

-   Agent uses `gdocs` CLI to read the document
-   Output contains the document text as markdown
-   Headings and formatting are preserved

--------------------------------------------------------------------------------

## Test 3: Read a spreadsheet

**Prompt:** "Can you find one of my spreadsheets and show me its contents?"

**Verify:**

-   Agent uses `gsheets` CLI to read spreadsheet data
-   Output shows tabular data from the spreadsheet
-   Multiple sheets are listed if they exist

--------------------------------------------------------------------------------

## Test 4: Show my calendar events

**Prompt:** "What meetings do I have coming up today?"

**Verify:**

-   Agent uses `gcalendar` CLI
-   Output lists upcoming calendar events with times and titles

--------------------------------------------------------------------------------

## Test 5: Read a presentation

**Prompt:** "Can you find one of my Google Slides presentations and show me
what's on each slide?"

**Verify:**

-   Agent uses `gslides` CLI
-   Output shows slide content as text
-   Slide numbers are indicated

--------------------------------------------------------------------------------

## Test 6: CSA semantic search

**Prompt:** "Search across my Gmail and Calendar for anything related to
project deadlines."

**Verify:**

-   Agent uses `csa_cli` to search across corpora
-   Results include relevant emails and/or calendar events
-   Citations are included in the output
