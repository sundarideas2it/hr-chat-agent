# HR Chat Agent

An assessment project for an authenticated HR assistant. Employees sign in, ask questions about company policy, and look up their own leave data. Document answers come from retrieval over HR policy files. Leave math and eligibility stay in deterministic Python, not in the language model.

Authentication, the local employee database, HR policy retrieval, and deterministic leave tools are implemented. LangGraph orchestration and the final chat workflow are not implemented yet.

Policy answers are generated only from the documents in `policies/`. The leave policy PDF already in that folder is ingested as provided and is not modified by the application.

## Overview

The application is a Streamlit chat UI in front of a LangGraph agent. After authentication, the agent may search policy documents, read the signed-in employee's records, calculate leave days, or check leave eligibility. Gemini handles language understanding and response writing. SQLite and plain Python functions handle employee data and HR rules.

## Assessment Objectives

The finished project will demonstrate:

- Authenticated employee access
- HR policy document question answering
- Retrieval-augmented generation over HR policy documents
- Agentic tool usage
- Employee-specific database queries
- Leave balance lookup
- Leave-day calculation
- Leave eligibility checking
- Conversational context
- Grounded responses
- A clear split between LLM reasoning and deterministic business logic

## Features

Planned behavior:

- Sign-in that establishes the current employee for the session
- Chat that keeps prior turns available to the agent
- Answers about HR policy that cite retrieved document passages
- Leave balance and leave history for the signed-in employee only
- A leave-day count computed by application code
- An eligibility result computed by application code
- Refusal to answer employee-specific questions for anyone other than the signed-in user

## Architecture

```
Employee
    |
    v
Streamlit UI
    |
    v
Authentication
    |
    v
LangGraph HR Agent
    |
    +-------------------+--------------------+-------------------+
    |                   |                    |
    v                   v                    v
Policy RAG        Employee DB Tools     HR Calculation Tools
    |                   |                    |
    v                   v                    v
ChromaDB             SQLite            Python Business Rules
    |
    v
Gemini LLM
```

See [architecture.md](architecture.md) for component responsibilities and a Mermaid diagram.

## Technology Stack

- Python 3.11+
- Streamlit
- LangGraph
- LangChain
- Google Gemini API (`langchain-google-genai`)
- SQLite
- ChromaDB
- pypdf
- python-dotenv

## Planned Agent Tools

| Tool | Role |
| --- | --- |
| `search_hr_policy` | Retrieve relevant passages from ingested HR policy documents. |
| `get_leave_balance` | Read the signed-in employee's current leave balance from SQLite. |
| `get_leave_history` | Read the signed-in employee's leave history from SQLite. |
| `calculate_leave_days` | Count leave days between two dates with deterministic business rules. |
| `check_leave_eligibility` | Decide whether a request is allowed using deterministic business rules. |

Authenticated employee identity will be derived from the application session. It will not be accepted as an arbitrary employee ID inside LLM-generated tool arguments. Tools that read personal records will use the session employee, so the model cannot ask for another employee's balance by supplying a different ID.

## Project Structure

```
hr-chat-agent/
├── app.py
├── agent/
│   ├── __init__.py
│   ├── graph.py
│   ├── prompts.py
│   └── state.py
├── tools/
│   ├── __init__.py
│   ├── policy_search.py
│   ├── leave_balance.py
│   ├── leave_calculator.py
│   └── eligibility.py
├── rag/
│   ├── __init__.py
│   ├── answer.py
│   ├── config.py
│   ├── errors.py
│   ├── ingest.py
│   └── retriever.py
├── database/
│   ├── __init__.py
│   ├── db.py
│   └── seed.py
├── policies/
│   └── README.md
├── tests/
│   ├── __init__.py
│   └── check_policy_rag.py
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
└── architecture.md
```

## Setup

Python 3.11 or newer is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set `GOOGLE_API_KEY` to your Gemini API key. Do not commit `.env`.

Build the local policy index from the documents in `policies/`, then start the app:

```bash
python -m rag.ingest
streamlit run app.py
```

Ingestion reads the policy PDFs in `policies/` and writes the Chroma index to `chroma_db/`, which is gitignored.

## Security Design

- `GOOGLE_API_KEY` is read from the environment. The repository ships `.env.example` with a placeholder only.
- `.env`, local databases, and the ChromaDB persist directory are gitignored.
- The signed-in employee is an application concern. Session state is set by authentication, then passed into tools by the application.
- Tool schemas will not treat employee ID as a free-form argument the model can choose.
- Policy answers are limited to retrieved document text. Employee-specific answers are limited to rows for the session employee.
- Leave-day counts and eligibility results are computed in Python. The model may explain those results; it does not calculate them.

## Demo Scenarios

These scenarios describe the intended demo. They are not executable yet.

1. An employee signs in and asks what the annual leave policy says. The agent retrieves the matching policy passage and answers from that text.
2. The same employee asks for their leave balance. The agent calls `get_leave_balance` for the session employee and reports the stored balance.
3. The employee asks how many leave days a date range covers. The agent calls `calculate_leave_days` and reports that function's result.
4. The employee asks whether they can take that leave. The agent calls `check_leave_eligibility` and explains the rule outcome.
5. The employee follows up with "what about next month?" The agent uses the conversation so far, still scoped to the signed-in employee.
