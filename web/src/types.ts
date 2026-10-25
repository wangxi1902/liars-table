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
  seq: number;
  kind: string;
  type: EventType;
  actor: string | null;
  text: string | null;
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
