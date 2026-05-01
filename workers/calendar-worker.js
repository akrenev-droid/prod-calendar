const UPSTREAM_URL =
  "https://raw.githubusercontent.com/akrenev-droid/prod_calendar/main/ru-production-calendar.ics";

function calendarPath(requestUrl) {
  const url = new URL(requestUrl);
  try {
    return decodeURIComponent(url.pathname).trim();
  } catch {
    return url.pathname.trim();
  }
}

export default {
  async fetch(request) {
    const path = calendarPath(request.url);
    if (path !== "/" && path !== "/calendar.ics" && path !== "/ru-production-calendar.ics") {
      return new Response("Not found", {
        status: 404,
        headers: { "Content-Type": "text/plain; charset=utf-8" },
      });
    }

    const upstream = await fetch(UPSTREAM_URL, {
      headers: { "User-Agent": "ru-prod-calendar-worker/1.0" },
      cf: { cacheEverything: true, cacheTtl: 600 },
    });

    if (!upstream.ok) {
      return new Response("Calendar temporarily unavailable", {
        status: 503,
        headers: { "Content-Type": "text/plain; charset=utf-8" },
      });
    }

    const calendar = await upstream.text();

    return new Response(calendar, {
      status: 200,
      headers: {
        "Content-Type": "text/calendar; charset=utf-8",
        "Content-Disposition": 'inline; filename="ru-production-calendar.ics"',
        "Cache-Control": "public, max-age=600",
        "Access-Control-Allow-Origin": "*",
        "X-Content-Type-Options": "nosniff",
      },
    });
  },
};
