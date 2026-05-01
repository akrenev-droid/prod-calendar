const SPREADSHEET_ID = "1CRtNewXjkHCsGT0K-X0BCcy2UhSjKh9_L9VdATt_Peg";
const CALENDAR_NAME = "Рабочий календарь";

const MONTH_SHEETS = [
  ["январь", 0, 1],
  ["февраль", 456860445, 2],
  ["март", 502245340, 3],
  ["апрель", 1088308748, 4],
  ["май", 1941514580, 5],
  ["июнь", 1251729376, 6],
  ["июль", 735698437, 7],
  ["август", 118471779, 8],
  ["сентябрь", 1598059560, 9],
  ["октябрь", 1029476715, 10],
  ["ноябрь", 210444841, 11],
  ["декабрь", 691612875, 12],
];

function csvUrl(gid) {
  return `https://docs.google.com/spreadsheets/d/${SPREADSHEET_ID}/gviz/tq?tqx=out:csv&gid=${gid}`;
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let inQuotes = false;

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    const next = text[i + 1];

    if (inQuotes) {
      if (char === '"' && next === '"') {
        cell += '"';
        i += 1;
      } else if (char === '"') {
        inQuotes = false;
      } else {
        cell += char;
      }
      continue;
    }

    if (char === '"') {
      inQuotes = true;
    } else if (char === ",") {
      row.push(cell);
      cell = "";
    } else if (char === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else if (char !== "\r") {
      cell += char;
    }
  }

  row.push(cell);
  rows.push(row);
  return rows;
}

function escapeText(value) {
  return String(value)
    .replaceAll("\\", "\\\\")
    .replaceAll(";", "\\;")
    .replaceAll(",", "\\,")
    .replaceAll("\r\n", "\\n")
    .replaceAll("\n", "\\n");
}

function foldLine(line) {
  const limit = 60;
  if (line.length <= limit) return [line];

  const lines = [];
  let rest = line;
  while (rest.length > limit) {
    lines.push(lines.length ? ` ${rest.slice(0, limit - 1)}` : rest.slice(0, limit));
    rest = rest.slice(lines.length === 1 ? limit : limit - 1);
  }
  lines.push(lines.length ? ` ${rest}` : rest);
  return lines;
}

function pushLine(lines, line) {
  lines.push(...foldLine(line));
}

function formatDate(year, month, day) {
  return `${year}${String(month).padStart(2, "0")}${String(day).padStart(2, "0")}`;
}

function nextDate(year, month, day) {
  const date = new Date(Date.UTC(year, month - 1, day));
  date.setUTCDate(date.getUTCDate() + 1);
  return [
    date.getUTCFullYear(),
    String(date.getUTCMonth() + 1).padStart(2, "0"),
    String(date.getUTCDate()).padStart(2, "0"),
  ].join("");
}

function event(lines, { uid, start, end, summary, description }) {
  lines.push("BEGIN:VEVENT");
  pushLine(lines, `UID:${uid}@planner26`);
  lines.push("DTSTAMP:20260101T000000Z");
  lines.push(`DTSTART;VALUE=DATE:${start}`);
  lines.push(`DTEND;VALUE=DATE:${end}`);
  pushLine(lines, `SUMMARY:${escapeText(summary)}`);
  if (description) {
    pushLine(lines, `DESCRIPTION:${escapeText(description)}`);
  }
  lines.push("TRANSP:TRANSPARENT");
  lines.push("END:VEVENT");
}

function dayStatusTitle(code) {
  if (code === "0") return "Рабочий день";
  if (code === "1") return "Выходной";
  if (code === "8") return "Праздник";
  if (code === "7") return "Сокращённый день";
  return code ? `День: ${code}` : "День";
}

function clean(value) {
  return String(value || "").trim();
}

function shortTask(value) {
  const firstLine = clean(value).split(/\r?\n/).map((line) => line.trim()).find(Boolean);
  if (!firstLine) return "Задача";
  return firstLine.length > 80 ? `${firstLine.slice(0, 77)}...` : firstLine;
}

function compactDescription(employee, task) {
  const normalized = clean(task)
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .join("\n");
  const value = `${employee}\n${normalized}`;
  return value.length > 280 ? `${value.slice(0, 277)}...` : value;
}

function streamText(value) {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      const chunkSize = 8192;
      for (let index = 0; index < value.length; index += chunkSize) {
        controller.enqueue(encoder.encode(value.slice(index, index + chunkSize)));
      }
      controller.close();
    },
  });
}

async function fetchMonth(sheet) {
  const [name, gid, month] = sheet;
  const response = await fetch(csvUrl(gid), {
    cf: { cacheEverything: true, cacheTtl: 300 },
  });
  if (!response.ok) {
    throw new Error(`Google Sheets CSV failed for ${name}: ${response.status}`);
  }
  return { name, month, rows: parseCsv(await response.text()) };
}

async function buildCalendar() {
  const months = await Promise.all(MONTH_SHEETS.map(fetchMonth));
  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Planner26 Work Calendar//RU",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
    `X-WR-CALNAME:${escapeText(CALENDAR_NAME)}`,
    `NAME:${escapeText(CALENDAR_NAME)}`,
    "X-WR-TIMEZONE:Europe/Moscow",
    "REFRESH-INTERVAL;VALUE=DURATION:PT15M",
    "X-PUBLISHED-TTL:PT15M",
  ];

  for (const monthData of months) {
    const rows = monthData.rows;
    const employees = rows[0] || [];
    const year = Number(clean(rows[1]?.[0])) || 2026;

    for (let rowIndex = 0; rowIndex < rows.length; rowIndex += 1) {
      const row = rows[rowIndex] || [];
      const day = Number(clean(row[0]));
      if (!day) continue;

      const code = clean(row[1]);
      const start = formatDate(year, monthData.month, day);
      const end = nextDate(year, monthData.month, day);
      const weekday = clean(row[2]);
      const tasks = [];

      for (let col = 4; col < employees.length; col += 1) {
        const employee = clean(employees[col]);
        const task = clean(row[col]);
        if (!employee || !task) continue;

        tasks.push(compactDescription(employee, task));
      }

      const description = [
        weekday ? `${day}.${String(monthData.month).padStart(2, "0")}.${year}, ${weekday}` : "",
        ...tasks,
      ].filter(Boolean).join("\n\n");

      event(lines, {
        uid: `${start}-day`,
        start,
        end,
        summary: dayStatusTitle(code),
        description,
      });
    }
  }

  lines.push("END:VCALENDAR");
  return `${lines.join("\r\n")}\r\n`;
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname !== "/" && url.pathname !== "/calendar.ics") {
      return new Response("Not found", {
        status: 404,
        headers: { "Content-Type": "text/plain; charset=utf-8" },
      });
    }

    try {
      const calendar = await buildCalendar();
      return new Response(streamText(calendar), {
        headers: {
          "Content-Type": "text/calendar; charset=utf-8",
          "Content-Disposition": 'inline; filename="planner26.ics"',
          "Cache-Control": "public, max-age=300",
          "Access-Control-Allow-Origin": "*",
          "X-Content-Type-Options": "nosniff",
        },
      });
    } catch (error) {
      return new Response(`Calendar temporarily unavailable: ${error.message}`, {
        status: 503,
        headers: { "Content-Type": "text/plain; charset=utf-8" },
      });
    }
  },
};
