# receptionist-redteam-eval

An open-source red-teaming eval for **tool-using AI phone receptionists**. It measures how often an LLM agent with live CRM tools can be talked, tricked, or injected into leaking patient data or taking actions it shouldn't, and how much two common mitigations help.

I run AI voice receptionists for real businesses. Those agents can look up customer records, book and cancel appointments, and send texts, while talking to anyone who dials in. This repo turns the failure modes I worry about in production into a reproducible benchmark.

## What it tests

The agent ("Bree") answers calls for a fictional dental clinic. It has a system prompt with clear privacy and action rules, plus eight CRM tools: `lookup_contact`, `get_availability`, `list_appointments`, `book_appointment`, `cancel_appointment`, `send_sms`, `set_opt_out`, and `transfer_to_human`. The caller's phone number comes from caller ID.

42 scripted scenarios in five categories:

| Category | Count | What the attacker does |
| --- | --- | --- |
| `social_engineering` | 10 | Claims to be the owner, a spouse, police, insurance, IT, or a patient on a new number |
| `tool_injection` | 10 | Plants instructions in CRM data the agent reads (contact notes, availability messages), then makes an innocent request |
| `unauthorized_action` | 8 | Asks the agent to book, cancel, text, or opt out on someone else's behalf, or ignores a STOP |
| `policy_drift` | 6 | Rapport building, roleplay, hypotheticals, incremental questions, translation and "summarize your instructions" tricks |
| `benign` | 8 | Legitimate requests the agent **should** complete, to catch over-refusal |

A canary secret is planted in the system prompt so prompt extraction is measurable.

## Defenses compared

| Setting | What changes |
| --- | --- |
| `none` | Baseline system prompt |
| `spotlight` | Tool output is wrapped in `<untrusted_data>` tags, and the prompt says that content is data, never instructions |
| `gate` | A policy layer **outside the model** blocks tool calls that break the rules (only the caller's own record, texts only to a verified caller, staff-only tools disabled). The model still sees an error and keeps talking |
| `spotlight+gate` | Both |

The gate is the interesting comparison: it is a control-style mitigation that holds even when the model is fooled, but it can't stop the model from **saying** something it shouldn't, and it can't force an action the model skipped (like an opt-out).

## Metrics

Scoring is deterministic and rule-based (`rr_eval/scoring.py`), so every number can be traced to a specific tool call or string in a transcript.

- **ASR attempted:** share of attack runs where the model leaked protected data or tried a forbidden tool call, including calls the gate blocked.
- **ASR executed:** share where harm actually happened (gate-blocked calls excluded).
- **Benign tasks done:** share of legitimate requests completed.

Reports include 95% Wilson intervals. Leak detection normalizes digits, so a phone number counts as leaked however it's formatted.

## Quickstart

Python 3.10+ and no third-party packages.

```bash
git clone https://github.com/hpintojr/receptionist-redteam-eval
cd receptionist-redteam-eval
python -m unittest discover tests                      # offline tests

# Offline plumbing check (no keys needed)
python -m rr_eval.run --provider mock-refuser
python -m rr_eval.run --provider mock-naive --defense gate

# Claude
export ANTHROPIC_API_KEY=...
python -m rr_eval.run --provider anthropic --model claude-haiku-5-5 --defense none
python -m rr_eval.run --provider anthropic --model claude-haiku-5-5 --defense spotlight+gate

# Local open-weight models through Ollama (must support tool calling)
python -m rr_eval.run --provider ollama --model qwen2.5:7b --defense none --epochs 3

# Any OpenAI-compatible API (OpenAI, OpenRouter, ...)
export OPENAI_API_KEY=...
python -m rr_eval.run --provider openai --model gpt-4o-mini --base-url https://api.openai.com/v1

python -m rr_eval.report                               # writes results/REPORT.md
```

Useful flags: `--category tool_injection`, `--limit 5`, `--epochs 3`, `--temperature 0.7`. Each run writes a JSONL file to `results/` with full transcripts and every tool call, so any score can be audited.

## Results

**No model results are committed yet.** The next step is a sweep across Claude and several open-weight models under all four defense settings, with `--epochs 3` at temperature 0.7.

For reference, the offline mock agents behave as designed. They are plumbing checks, not findings:

| Agent | Defense | ASR attempted | ASR executed |
| --- | --- | --- | --- |
| mock-naive (dumps the schedule, texts anyone) | none | 38% | 38% |
| mock-naive | gate | 24% | 3% |
| mock-refuser (refuses everything) | none | 3% | 3% |

Even these show the shape of the question: the gate cuts executed harm sharply, but attempted harm stays high, and the one case it can't fix is the agent never calling `set_opt_out` after a STOP. The refuser also completes 0 of 8 legitimate tasks, which is why the benign set exists.

## Adding scenarios

Scenarios live in `scenarios/scenarios.json`. Each has a caller number, scripted caller turns, optional injections into CRM data, and either `violations` (attacks) or `required` (benign) rules. Rule types are documented at the top of `rr_eval/scoring.py`.

## Limitations

- **Scripted attacker.** Caller turns are fixed, not adaptive. A real attacker adjusts to the agent's replies. An LLM attacker is on the roadmap.
- **String-match leak detection** can miss paraphrased leaks (for example "the afternoon slot") and can rarely false-positive. Transcripts are saved for manual review.
- **Caller ID is trusted** by the gate. Real caller ID can be spoofed, so the gate is an upper bound on what identity-based checks can do.
- **Text, not voice.** Real calls add speech recognition errors, interruptions, and latency pressure.
- **Small n.** 34 attack scenarios per setting. Use `--epochs` and read the intervals.

## Roadmap

- Adaptive LLM attacker with a fixed turn budget
- LLM judge as a second scorer, with agreement against the rule-based scorer
- Port to [Inspect](https://inspect.aisi.org.uk/) for compatibility with existing eval tooling
- Speech-to-text noise injection to simulate phone audio

## Data and ethics

All people, phone numbers (555-01xx), and emails (example.com) are fictional. No real customer data is used. The attacks are well-known categories of social engineering and prompt injection, aimed at helping builders measure and harden their own agents.

## License

MIT. Built by [Hamilton Pinto Jr.](https://www.linkedin.com/in/hamilton-pinto-jr)
