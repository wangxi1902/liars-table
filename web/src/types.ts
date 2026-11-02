export type EventType = "speech" | "vote" | "death" | "system";

/** 一个座位。前四项由后端生成并保证确定性（同 seed 同名字）。 */
export interface Player {
  seat: string;
  name: string;
  emoji: string;
  hue: number;
  role?: string;
  survived?: boolean;
}

/** WebSocket 推来的一条事件。 */
export interface FeedEvent {
  stream_seq: number;
  seq: number;
  kind: string;
  type: EventType;
  actor: string | null;
  text: string | null;
}

export interface DecisionTrace {
  seat: string;
  decision_kind: string;
  node: string;
  status: "started" | "completed" | "failed" | "timed_out" | "skipped";
  summary: string;
  elapsed_ms: number;
  steps_used: number;
  model_calls: number;
}

export interface ThoughtEvidence {
  event_id: number;
  kind: "statement" | "vote_pattern" | "role_claim" | "behavior";
  summary: string;
  reason: string;
  delta: number;
}

export interface PlayerAssessment {
  seat: string;
  suspicion: number;
  recent_delta: number;
  evidence: ThoughtEvidence[];
}

export interface DecisionBasis {
  decision_id: string;
  seat: string;
  decision_kind: string;
  focus_players: PlayerAssessment[];
  planned_target: string | null;
  visibility: "public";
}

export interface DecisionTraceEvent {
  stream_seq: number;
  kind: "decision_trace";
  trace: DecisionTrace;
}

export interface DecisionBasisEvent {
  stream_seq: number;
  kind: "decision_basis";
  basis: DecisionBasis;
}

export type StreamEvent = FeedEvent | DecisionTraceEvent | DecisionBasisEvent;

export interface ThoughtState {
  seat: string;
  phase: string;
  basis: DecisionBasis | null;
}

/** 终局信息。 */
export interface ResultData {
  winner: string;
  reason: string;
  rounds: number;
  players: Player[];
}

/** 前端列表里的一条消息（text 会随打字机增长）。 */
export interface Entry {
  id: number;
  type: EventType;
  kind: string;
  actor: string | null;
  text: string;
}
