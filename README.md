# Ramat Utsav — Sports Event ERP System
### Built for Vivekananda Kendra, Rajkot

A full-stack internal web application built to manage **Ramat Utsav 2026**, an annual inter-school sports event. Replaced manual coordination via spreadsheets and WhatsApp with a centralized, role-based digital system.

---

## The Problem It Solves

Before this system, the event was managed through spreadsheets, WhatsApp groups, and in-person coordination — leading to scheduling conflicts, duplicate registrations, and significant overhead for organizers. This application centralizes the entire workflow from student registration to result recording.

---

## Features

**Event Setup (Admin)**
- Create and manage games (Individual, Team, Baudhik) with configurable team sizes and round capacities
- Schedule game events with automatic conflict detection for location and group time clashes
- Manage locations, age groups (Sanskarvargs), and student groups by standard range

**Student Registration (Vargshikshak)**
- Role-restricted registration portal — each teacher only sees and manages their own Sanskarvarg
- Students registered with auto-generated unique IDs (`XXX-DDMMYYYY-NNN`)
- Game participation selection with team assignment for team events
- Draft save and final submit with submission locking

**Scheduling & Reports**
- Auto-distribution of students into rounds with even distribution across rounds
- Students from the same Sanskarvarg kept together where possible
- Drag-and-drop round reassignment post-generation
- Printable PDF schedule slips per student and per Sanskarvarg

**Results & Leaderboard**
- Record 1st, 2nd, 3rd positions per event (individual and team)
- Student-wise points leaderboard with tie handling
- Event-wise results summary
- Exportable combined PDF report

---

## Role-Based Access Control

| Role | Access |
|------|--------|
| `UtsavPramukh` | Full access — all setup, reports, results, user management |
| `Sanchalan` | Game and event management |
| `Vargshikshak` | Student registration for assigned Sanskarvargs only |

---

## Tech Stack

- **Backend:** Python, Flask, Flask-SQLAlchemy, Flask-Login
- **Database:** MySQL
- **Auth:** Session-based login, Werkzeug password hashing
- **Frontend:** HTML, CSS, Jinja2, JavaScript
- **Architecture:** Multi-user, network-accessible (deployed on local LAN)

---

## Database Schema

5 core entities with relational integrity:

```
User → VargshikshakSanskarvarg → Sanskarvarg
Sanskarvarg → Student → Participation → GameEvent
GameEvent → Game, Group, Location
GameEvent → EventResult
Student → StudentCounter (for ID generation)
GameEvent → SubmissionStatus
```

---

## Local Setup

### Prerequisites
- Python 3.8+
- MySQL 8.0+

### Steps

1. **Clone the repository:**
   ```bash
   git clone https://github.com/veermehta270/ramat-utsav-erp.git
   cd ramat-utsav-erp
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate      # Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up your MySQL database:**
   ```sql
   CREATE DATABASE RamatUtsav;
   ```

5. **Configure environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env with your actual MySQL credentials
   ```

6. **Create database tables:**
   ```bash
   flask shell
   >>> from models import db
   >>> db.create_all()
   >>> exit()
   ```

7. **Run the app:**
   ```bash
   python app.py
   ```
   App runs at `http://0.0.0.0:5050` — accessible from any device on the same network.

---

## Key Engineering Decisions

**Round Distribution Algorithm** — Students are distributed across rounds using a balanced algorithm that minimizes variance in round sizes while keeping students from the same Sanskarvarg together, improving fairness and logistics.

**Conflict Detection** — Before any game event is scheduled, the system checks both location availability and group availability across overlapping time windows, preventing double-bookings automatically.

**Submission Locking** — Once a Vargshikshak submits their registration, it is locked and cannot be edited without an admin unlock. This prevents last-minute changes from affecting generated reports.

**Unique Student ID Generation** — Each student gets a deterministic ID based on their Sanskarvarg abbreviation, date of birth, and a per-Sanskarvarg counter, making IDs human-readable and traceable.

---

## Screenshots

*(Add screenshots here)*

---

## Notes

- The `.env` file containing database credentials is excluded from this repository. Use `.env.example` as a template.
- The database is not included. Run `db.create_all()` to initialize the schema on first run.
- This was a self-initiated project built during Dec 2025 – Jan 2026 and deployed live for Ramat Utsav 2026.