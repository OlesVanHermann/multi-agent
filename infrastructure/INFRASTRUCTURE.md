# Multi-Agent Infrastructure

Multi-agent AI orchestration with Claude Code.

## Quick Setup

### Local Development (Standalone)
```bash
cd multi-agent/infrastructure
./setup.sh
# Choose option 1 (Standalone)
./multi-agent.sh start standalone
```

### Multi-VM Setup
```bash
cd multi-agent/infrastructure
./setup.sh
# Choose option 2 (Full)
# Enter VM IP, SSH user, key path
./multi-agent.sh start full
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  MAC                                │  VM                           │
│                                     │                               │
│  ┌─────────────┐    SSH Tunnel      │  ┌─────────────┐             │
│  │   Redis     │◄──────────────────►│  │   Redis     │             │
│  │  (Docker)   │                    │  │  (Docker)   │             │
│  └─────────────┘                    │  └─────────────┘             │
│        ▲                            │        ▲                      │
│        │                            │        │                      │
│  ┌─────┴─────┐                      │  ┌─────┴─────┐  ┌──────────┐│
│  │  SUPER-   │                      │  │  MASTER   │  │ SLAVES   ││
│  │  MASTER   │                      │  │           │  │ (1..N)   ││
│  │           │                      │  │           │  │          ││
│  │ (Claude)  │                      │  │ (Claude)  │  │ (Claude) ││
│  └───────────┘                      │  └───────────┘  └──────────┘│
│                                     │                               │
└─────────────────────────────────────────────────────────────────────┘
```

## Dashboard (http://127.0.0.1:8080)

```
┌─────────────┬──────────────────────────────────────────┐
│ Agents      │  ◆ SUPER-MASTER                     30%  │
│             │  [conversation...]                       │
│ ○ slave-01  │  [input] [Send]                         │
│ ○ slave-02  ├──────────────────────────────────────────┤
│ ○ slave-03  │  ◆ MASTER                           30%  │
│ ○ slave-04  │  [conversation...]                       │
│             │  [input] [Send]                         │
│ (click to   ├──────────────────────────────────────────┤
│  scroll)    │  ◆ SLAVES                           40%  │
│             │  ┌─slave-01─┐ ┌─slave-02─┐ ┌─slave-03─┐ │
│             │  │[convo]   │ │[convo]   │ │[convo]   │ │
│             │  │[input]   │ │[input]   │ │[input]   │ │
│             │  └──────────┘ └──────────┘ └──────────┘ │
└─────────────┴──────────────────────────────────────────┘
```

## Commands

### RW / RO (Read-Write / Read-Only)

```bash
# Terminal mode
./multi-agent.sh RW super-master      # Interactive session
./multi-agent.sh RO master            # Watch only

# Send message
./multi-agent.sh RW master "do X"     # Send and exit
./multi-agent.sh RO master "do X"     # ERROR (read-only)

# Watch multiple
./multi-agent.sh RO 'slave*'          # All slaves
```

### Agents

```bash
./multi-agent.sh agent --role super-master
./multi-agent.sh agent --role master
./multi-agent.sh agent --role slave --id slave-01

./multi-agent.sh list                  # List all agents
./multi-agent.sh kill slave-03         # Remove agent
./multi-agent.sh clear master          # Clear conversation
./multi-agent.sh logs master 100       # View last 100 messages
```

### Infrastructure

```bash
./multi-agent.sh start standalone      # Redis only
./multi-agent.sh start full            # Redis + Dashboard + Bridge

./multi-agent.sh stop
./multi-agent.sh status
```

### Projects & Tasks

```bash
./multi-agent.sh new-project myproject
./multi-agent.sh activate myproject
./multi-agent.sh projects

./multi-agent.sh task "Analyze the code in /src"
./multi-agent.sh result task-12345
```

### Stats & Export

```bash
./multi-agent.sh stats                 # Global statistics
./multi-agent.sh export                # Export results to JSON
```

## Complete Workflow

### 1. Setup Infrastructure

```bash
cd multi-agent/infrastructure
./setup.sh
./multi-agent.sh start standalone
```

### 2. Start Agents

```bash
# Terminal 1 - Master
./multi-agent.sh agent --role master

# Terminal 2 - Slave
./multi-agent.sh agent --role slave --id slave-01

# Terminal 3 - Another Slave
./multi-agent.sh agent --role slave --id slave-02
```

### 3. Monitor & Control

```bash
# Watch from another terminal
./multi-agent.sh RO master
./multi-agent.sh RO 'slave*'

# Send commands
./multi-agent.sh RW master "prioritize task X"

# Dashboard (if using full mode)
open http://127.0.0.1:8080
```

## Files

```
multi-agent/
├── infrastructure/
│   ├── setup.sh                    # Run this first
│   ├── multi-agent.sh              # CLI
│   ├── docker-compose.yml          # Redis + Dashboard + Bridge
│   ├── docker-compose.standalone.yml # Redis only
│   └── .env.mac                    # VM connection config (created by setup)
│
├── core/
│   ├── agent-runner/               # Claude Code wrapper
│   ├── dashboard/                  # Web UI
│   └── bridge/                     # SSH sync (Mac→VM)
│
├── prompts/                        # Agent prompts
├── scripts/                        # Orchestration scripts
└── docs/
    └── CLI.md                      # Full CLI reference
```

## Ports (127.0.0.1 only)

| Port | Service |
|------|---------|
| 6379 | Redis |
| 8080 | Dashboard |

All ports bound to `127.0.0.1` only (secure).

## Redis Keys

| Key | Description |
|-----|-------------|
| `ma:agents` | Hash of connected agents |
| `ma:inject:{id}` | Injection queue for agent |
| `ma:conversation:{id}` | Conversation history |
| `ma:conversation:{id}:live` | Real-time stream |
| `ma:tasks:{project}` | Task queue |
| `ma:results:{task_id}` | Task results |
