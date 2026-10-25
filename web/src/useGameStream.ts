import { useCallback, useEffect, useRef, useState } from "react";
import type { Entry, FeedEvent, Player, ResultData } from "./types";

type Status = "idle" | "connecting" | "playing" | "done" | "error";

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * 把 WebSocket 的事件流变成"能一条条播放"的界面状态。
 *
 * 为什么要队列 + 打字机，而不是收到就渲染？
 *   一局 40 秒、20 多条发言，事件是瞬时连发的。直接渲染会"刷"一下全出来，
 *   "谁在说话"的高亮根本看不见。队列让节奏由前端控制，后端不用改。
 */
export function useGameStream() {
  const [players, setPlayers] = useState<Player[]>([]);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [dead, setDead] = useState<string[]>([]);
  const [status, setStatus] = useState<Status>("idle");
  const [seed, setSeed] = useState<number | null>(null);
  const [result, setResult] = useState<ResultData | null>(null);

  const socket = useRef<WebSocket | null>(null);
  const queue = useRef<FeedEvent[]>([]);
  const busy = useRef(false);
  const generation = useRef(0);
  const lastSeq = useRef(-1);
  const finished = useRef(false);
  const drainRef = useRef<() => Promise<void>>(async () => {});

  /** 一个字一个字地写进某条消息。step 越大越快。 */
  const typeInto = useCallback(async (id: number, full: string, gen: number) => {
    const step = 2;
    for (let end = step; end <= full.length + step; end += step) {
      if (generation.current !== gen) return;
      const text = full.slice(0, end);
      setEntries((list) => list.map((item) => (item.id === id ? { ...item, text } : item)));
      await sleep(18);
    }
  }, []);

  /** 消费队列：一条播完再播下一条。 */
  const drain = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    const gen = generation.current;

    while (queue.current.length > 0 && generation.current === gen) {
      const event = queue.current.shift();
      if (!event || !event.text) continue;

      // 有人出局：让底部头像变灰
      if ((event.kind === "player_died" || event.kind === "exiled") && event.actor) {
        const seat = event.actor;
        setDead((prev) => (prev.includes(seat) ? prev : [...prev, seat]));
      }

      if (event.type === "speech") {
        setActive(event.actor);
        setEntries((list) => [
          ...list,
          { id: event.seq, type: event.type, kind: event.kind, actor: event.actor, text: "" },
        ]);
        await typeInto(event.seq, event.text, gen);
        await sleep(220);
      } else {
        setEntries((list) => [
          ...list,
          {
            id: event.seq,
            type: event.type,
            kind: event.kind,
            actor: event.actor,
            text: event.text as string,
          },
        ]);
        await sleep(event.type === "system" ? 300 : 140);
      }
    }

    if (generation.current === gen) setActive(null);
    busy.current = false;
    if (queue.current.length > 0) void drainRef.current();
  }, [typeInto]);

  drainRef.current = drain;

  const connect = useCallback((gameId: string) => {
    socket.current?.close();
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${scheme}://${location.host}/ws/${gameId}`);
    socket.current = ws;

    ws.onopen = () => setStatus("playing");
    ws.onerror = () => setStatus("error");
    ws.onclose = () => {
      if (!finished.current) setStatus("error");
    };
    ws.onmessage = (raw: MessageEvent<string>) => {
      const message = JSON.parse(raw.data) as Record<string, unknown>;

      if (message.kind === "roster") {
        setPlayers(message.players as Player[]);
        return;
      }
      if (message.kind === "result") {
        finished.current = true;
        setResult(message as unknown as ResultData);
        setStatus("done");
        return;
      }

      const event = message as unknown as FeedEvent;
      if (event.seq <= lastSeq.current) return; // 重连去重
      lastSeq.current = event.seq;
      queue.current.push(event);
      void drainRef.current();
    };
  }, []);

  const start = useCallback(async () => {
    generation.current += 1;
    queue.current = [];
    busy.current = false;
    lastSeq.current = -1;
    finished.current = false;
    setEntries([]);
    setActive(null);
    setDead([]);
    setResult(null);
    setStatus("connecting");

    try {
      const response = await fetch("/api/games", { method: "POST" });
      const data = (await response.json()) as {
        id: string;
        seed: number;
        players: Player[];
      };
      setSeed(data.seed);
      setPlayers(data.players);
      connect(data.id);
    } catch {
      setStatus("error");
    }
  }, [connect]);

  /** 回放模式：`?id=xxx` 直接把这一局的历史铺出来，不逐条播放。 */
  const attach = useCallback(
    async (gameId: string) => {
      generation.current += 1;
      try {
        const response = await fetch(`/api/games/${gameId}`);
        if (!response.ok) {
          setStatus("error");
          return;
        }
        const data = (await response.json()) as {
          seed: number;
          players: Player[];
          status: string;
          payloads: FeedEvent[];
          summary: ResultData | null;
        };

        setSeed(data.seed);
        setPlayers(data.players);

        const list: Entry[] = [];
        const gone: string[] = [];
        let lastSpeaker: string | null = null;
        for (const item of data.payloads) {
          if (!item.text) continue;
          list.push({
            id: item.seq,
            type: item.type,
            kind: item.kind,
            actor: item.actor,
            text: item.text,
          });
          if ((item.kind === "player_died" || item.kind === "exiled") && item.actor) {
            if (!gone.includes(item.actor)) gone.push(item.actor);
          }
          if (item.type === "speech") lastSpeaker = item.actor;
        }

        setEntries(list);
        setDead(gone);
        // 关键：把游标推到已加载的最后一条，否则 WebSocket 补发历史时会重复渲染
        lastSeq.current = data.payloads.length > 0 ? data.payloads[data.payloads.length - 1].seq : -1;
        // 停在最后一个发言者身上：回放页也能看出"谁在说话"
        setActive(lastSpeaker);

        if (data.summary && data.summary.winner) {
          setResult(data.summary);
          setStatus("done");
          finished.current = true;
        } else {
          setStatus("playing");
          connect(gameId);
        }
      } catch {
        setStatus("error");
      }
    },
    [connect],
  );

  useEffect(() => {
    const preset = new URLSearchParams(location.search).get("id");
    if (preset) {
      void attach(preset);
    } else {
      void start();
    }
    return () => socket.current?.close();
  }, [attach, start]);

  return { players, entries, active, dead, status, seed, result, start };
}
