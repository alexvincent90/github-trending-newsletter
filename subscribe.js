/**
 * Netlify Function: subscribe.js
 * Adds an email to Resend Audience when someone submits the signup form.
 * Env vars needed in Netlify dashboard:
 *   RESEND_API_KEY
 *   RESEND_AUDIENCE_ID
 */

exports.handler = async (event) => {
  if (event.httpMethod !== "POST") {
    return { statusCode: 405, body: JSON.stringify({ error: "Method not allowed" }) };
  }

  let email;
  try {
    ({ email } = JSON.parse(event.body));
  } catch {
    return { statusCode: 400, body: JSON.stringify({ error: "Invalid request body" }) };
  }

  // Basic email validation
  const emailRe = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  if (!email || !emailRe.test(email)) {
    return { statusCode: 400, body: JSON.stringify({ error: "Invalid email address" }) };
  }

  const RESEND_API_KEY   = process.env.RESEND_API_KEY;
  const RESEND_AUDIENCE_ID = process.env.RESEND_AUDIENCE_ID;

  if (!RESEND_API_KEY || !RESEND_AUDIENCE_ID) {
    console.error("Missing env vars");
    return { statusCode: 500, body: JSON.stringify({ error: "Server misconfiguration" }) };
  }

  try {
    const res = await fetch(
      `https://api.resend.com/audiences/${RESEND_AUDIENCE_ID}/contacts`,
      {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${RESEND_API_KEY}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ email, unsubscribed: false }),
      }
    );

    if (res.status === 409) {
      // Already subscribed — treat as success
      return { statusCode: 200, body: JSON.stringify({ ok: true }) };
    }

    if (!res.ok) {
      const err = await res.json();
      console.error("Resend error:", err);
      return { statusCode: 500, body: JSON.stringify({ error: "Failed to subscribe. Please try again." }) };
    }

    return { statusCode: 200, body: JSON.stringify({ ok: true }) };
  } catch (err) {
    console.error("Fetch error:", err);
    return { statusCode: 500, body: JSON.stringify({ error: "Network error" }) };
  }
};
