# Video demo

A captioned walkthrough assembled from screenshots of real app interactions. It is not a continuous screen recording. The demo uses an isolated server on port 8766; normal usage is port 8765. No new approval, external message, or job application was sent.

[Play the video](approval-helper-demo.mp4)

## 00:00 — Codex Approval Helper

A walkthrough of the features that work today. Real app screenshots, paced with captions. No new approval is sent in this recording.

## 00:08 — 1 / Launch the local app

Run python3 app.py and open http://127.0.0.1:8765. The helper starts paused. This recording uses port 8766 and separate demo settings.

## 00:16 — 2 / Connect to Codex

Click Connect to Codex. Your installed CLI supplies chat identity and saved history. Allow the chat list a moment to load.

## 00:23 — 3 / Select a chat and define a rule

Select only the chat you want monitored. Enter the complete question and the offered response you authorize, then Save settings.

## 00:33 — Optional / Add a missing chat by ID

Expand Chat missing from the list? Paste its Codex thread ID and click Add chat by ID. The helper reads the actual title from Codex.

## 00:41 — 4 / Start with read-only preview

Choose Read-only preview, then Start monitoring. The latest saved message appears. No exact match means no proposed response; preview never sends anything.

## 00:51 — 5 / Pause before changing behavior

Click Pause. Future checks stop after the current check. Saving settings also pauses monitoring. Pause does not stop Codex work already underway.

## 00:58 — 6 / Enable desktop offered-choice responses

Choose Answer matching desktop questions and save. Keep the selected chat open in one Codex window, with a unique title. Use an exact offered choice.

## 01:08 — 7 / Monitor live question cards

Click Start monitoring. A matching live single-question card receives its offered answer once. Here the test is already complete, so the helper sends no response.

## 01:18 — 8 / Leave monitoring paused when finished

Click Pause. Attempts are recorded before sending and are never retried automatically. Unconfirmed delivery pauses monitoring for manual review.

## 01:26 — Current limits

Verified: desktop offered choices, previews, saved rules, Pause and duplicate prevention. Custom text is blocked on this Wayland session. Browser, dot, multi-question and tool-dialog paths remain unfinished.
