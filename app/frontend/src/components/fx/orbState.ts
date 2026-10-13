import type { OrbState } from 'thinking-orbs'
import type { AgentName, Message } from '@/types/chat'

const AGENT_ORB: Record<AgentName, OrbState> = {
  Orchestrator: 'connecting',
  Researcher: 'searching',
  Checker: 'solving',
}

export function agentOrbState(agent: AgentName): OrbState {
  return AGENT_ORB[agent]
}

/** The orb animation for what a live run is doing right now. */
export function runOrbState(message: Message): OrbState {
  if (message.runStatus === 'waiting') return 'breathing'
  if (message.runStatus === 'writing') return 'composing'
  const running = message.trace?.findLast((s) => s.running)
  return running ? agentOrbState(running.agent) : 'working'
}
