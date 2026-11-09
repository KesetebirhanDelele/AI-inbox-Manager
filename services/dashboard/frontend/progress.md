
### 2026-11-09: Remove button on Settings > Agents (branch `feat/remove-agent-button`)
- Kes: agents should be addable and removable like the people-who-can-sign-in list. Remove clears the agent's email (their students' cards then go to the approver). An agent named on the roster sheet stays listed with an empty email (the sheet owns that list); a hand-added agent with no roster students disappears. `AgentsCard.tsx` only (the API already clears with an empty email). One new test.
