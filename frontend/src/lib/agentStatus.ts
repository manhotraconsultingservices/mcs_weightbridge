/**
 * Local scale-agent status → weight reading.
 *
 * Kept separate from useWeight so it stays dependency-free and directly
 * testable: this is where the two rules live that fail silently and only show
 * up as a wrong number in front of a driver.
 */

/** Where the reading on screen came from. */
export type WeightSource = 'cloud' | 'local' | 'none';

export interface WeightReading {
  weight_kg: number;
  is_stable: boolean;
  stable_duration_sec: number;
  scale_connected: boolean;
  /** 'local' = read directly from the scale agent on this PC (internet down). */
  source: WeightSource;
}

/** Shape of the scale agent's GET /status payload (the fields we consume). */
export interface AgentStatus {
  service?: string;
  scale_connected?: boolean;
  last_weight_kg?: number;
  is_stable?: boolean;
  stable_duration_sec?: number;
  agent_version?: string;
}

/** A true blank — shown when no source is live. */
export const IDLE: WeightReading = {
  weight_kg: 0,
  is_stable: false,
  stable_duration_sec: 0,
  scale_connected: false,
  source: 'none',
};

/**
 * Rules that matter:
 *  - `last_weight_kg` is -1 until the agent has parsed its first frame, so a
 *    naive Number() would render "-1 kg" on the bridge.
 *  - If the agent is reachable but its serial port is down, fall back to IDLE
 *    (a blank) — never to the last known weight. A frozen number next to a
 *    truck is worse than an obvious "no reading".
 *  - 0 kg is a VALID reading (empty bridge), not an absent one.
 */
export function agentStatusToReading(data: AgentStatus | null): WeightReading {
  const kg = Number(data?.last_weight_kg ?? -1);
  if (!data?.scale_connected || !Number.isFinite(kg) || kg < 0) return IDLE;
  return {
    weight_kg: kg,
    is_stable: !!data.is_stable,
    stable_duration_sec: Number(data.stable_duration_sec) || 0,
    scale_connected: true,
    source: 'local',
  };
}
