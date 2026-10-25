import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { useGameStream } from "./useGameStream";
import type { Entry, Player, ResultData } from "./types";

function hueStyle(hue: number | undefined): CSSProperties {
  return { "--hue": hue ?? 210 } as CSSProperties;
}

function Message({ entry, player }: { entry: Entry; player?: Player }) {
  if (entry.type !== "speech") {
    const className =
      entry.type === "death" ? "sys death" : entry.type === "vote" ? "sys vote" : "sys";
    return <div className={className}>{entry.text}</div>;
  }

  return (
    <div className="msg">
      <div className="mini" style={hueStyle(player?.hue)}>
        {player?.emoji ?? "🙂"}
      </div>
      <div className="bubble">
        <div className="who">{player?.name ?? entry.actor}</div>
        <div className="txt">{entry.text}</div>
      </div>
    </div>
  );
}

function ResultOverlay({
  data,
  onClose,
  onRestart,
}: {
  data: ResultData;
  onClose: () => void;
  onRestart: () => void;
}) {
  const wolvesWin = data.winner === "wolf";
  return (
    // 点空白处也能关：判断 target === currentTarget，避免点卡片内部时误关
    <div
      className="overlay"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className={`result ${wolvesWin ? "wolf" : "good"}`}>
        <button className="close" onClick={onClose} aria-label="关闭结算">
          ✕
        </button>
        <h2>{wolvesWin ? "狼人阵营获胜" : "好人阵营获胜"}</h2>
        <p className="reason">{data.reason}</p>
        <div className="roles">
          {data.players.map((player) => (
            <div key={player.seat} className="role-row">
              <span className="r-emoji" style={hueStyle(player.hue)}>
                {player.emoji}
              </span>
              <span className="r-name">{player.name}</span>
              <span className={`r-role ${player.role === "狼人" ? "wolf" : "good"}`}>
                {player.role}
              </span>
              <span className="r-state">{player.survived ? "存活" : "出局"}</span>
            </div>
          ))}
        </div>
        <button className="btn primary" onClick={onRestart}>
          再来一局
        </button>
        <p className="hint-close">按 Esc 或点击空白处可以关闭，继续回看聊天记录</p>
      </div>
    </div>
  );
}

export default function App() {
  const { players, entries, active, dead, status, seed, result, start } = useGameStream();
  const feedRef = useRef<HTMLDivElement>(null);
  const [showResult, setShowResult] = useState(false);

  // 结算一出现就自动弹；用户手动关掉后不会被重新弹回来（result 对象没变）
  useEffect(() => {
    setShowResult(Boolean(result));
  }, [result]);

  // Esc 关闭
  useEffect(() => {
    if (!showResult) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setShowResult(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [showResult]);

  const bySeat = useMemo(() => {
    const map: Record<string, Player> = {};
    for (const player of players) map[player.seat] = player;
    return map;
  }, [players]);

  useEffect(() => {
    const feed = feedRef.current;
    if (feed) feed.scrollTop = feed.scrollHeight;
  }, [entries]);

  const statusText: Record<string, string> = {
    idle: "准备中",
    connecting: "开局中…",
    playing: "对局进行中",
    done: "已结束",
    error: "连接断开",
  };

  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <h1>Liar&apos;s Table</h1>
          <span className="sub">9 人局 · seed {seed ?? "-"}</span>
        </div>
        <div className="top-right">
          <span className={`dot ${status}`} />
          <span className="status">{statusText[status] ?? status}</span>
          {result && !showResult && (
            <button className="btn" onClick={() => setShowResult(true)}>
              查看结算
            </button>
          )}
          <button className="btn" onClick={() => void start()}>
            新开一局
          </button>
        </div>
      </header>

      <main className="feed" ref={feedRef}>
        <div className="spacer" />
        {entries.length === 0 && <div className="hint">正在发牌…</div>}
        {entries.map((entry) => (
          <Message key={entry.id} entry={entry} player={entry.actor ? bySeat[entry.actor] : undefined} />
        ))}
      </main>

      <footer className="dock">
        {players.map((player) => {
          const classes = ["chip"];
          if (active === player.seat) classes.push("active");
          if (dead.includes(player.seat)) classes.push("dead");
          return (
            <div key={player.seat} className={classes.join(" ")} style={hueStyle(player.hue)}>
              <div className="face">{player.emoji}</div>
              <div className="nm">{player.name}</div>
            </div>
          );
        })}
      </footer>

      {result && showResult && (
        <ResultOverlay
          data={result}
          onClose={() => setShowResult(false)}
          onRestart={() => void start()}
        />
      )}
    </div>
  );
}
