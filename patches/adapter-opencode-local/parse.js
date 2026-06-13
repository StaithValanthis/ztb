import { asNumber, asString, parseJson, parseObject } from "@paperclipai/adapter-utils/server-utils";
const OPENCODE_TRANSIENT_UPSTREAM_RE = /(?:rate[-\s]?limit(?:ed)?|rate_limit_error|too\s+many\s+requests|\b429\b|overloaded(?:_error)?|server\s+overloaded|service\s+unavailable|\b503\b|\b529\b|high\s+demand|try\s+again\s+later|temporarily\s+unavailable|throttl(?:ed|ing)|upstream\s+error|upstream\s+unavailable|connection\s+refused|connection\s+reset|econnrefused|econnreset|internal\s+server\s+error|bad\s+gateway|\b502\b|service\s+temporarily\s+unavailable)/i;
function errorText(value) {
    if (typeof value === "string")
        return value;
    const rec = parseObject(value);
    const message = asString(rec.message, "").trim();
    if (message)
        return message;
    const data = parseObject(rec.data);
    const nestedMessage = asString(data.message, "").trim();
    if (nestedMessage)
        return nestedMessage;
    const name = asString(rec.name, "").trim();
    if (name)
        return name;
    const code = asString(rec.code, "").trim();
    if (code)
        return code;
    try {
        return JSON.stringify(rec);
    }
    catch {
        return "";
    }
}
export function parseOpenCodeJsonl(stdout) {
    let sessionId = null;
    const messages = [];
    const errors = [];
    const toolErrors = [];
    const usage = {
        inputTokens: 0,
        cachedInputTokens: 0,
        outputTokens: 0,
    };
    let costUsd = 0;
    for (const rawLine of stdout.split(/\r?\n/)) {
        const line = rawLine.trim();
        if (!line)
            continue;
        const event = parseJson(line);
        if (!event)
            continue;
        const currentSessionId = asString(event.sessionID, "").trim();
        if (currentSessionId)
            sessionId = currentSessionId;
        const type = asString(event.type, "");
        if (type === "text") {
            const part = parseObject(event.part);
            const text = asString(part.text, "").trim();
            if (text)
                messages.push(text);
            continue;
        }
        if (type === "step_finish") {
            const part = parseObject(event.part);
            const tokens = parseObject(part.tokens);
            const cache = parseObject(tokens.cache);
            usage.inputTokens += asNumber(tokens.input, 0);
            usage.cachedInputTokens += asNumber(cache.read, 0);
            usage.outputTokens += asNumber(tokens.output, 0) + asNumber(tokens.reasoning, 0);
            costUsd += asNumber(part.cost, 0);
            continue;
        }
        if (type === "tool_use") {
            const part = parseObject(event.part);
            const state = parseObject(part.state);
            if (asString(state.status, "") === "error") {
                const text = asString(state.error, "").trim();
                if (text)
                    toolErrors.push(text);
            }
            continue;
        }
        if (type === "error") {
            const text = errorText(event.error ?? event.message).trim();
            if (text)
                errors.push(text);
            continue;
        }
    }
    return {
        sessionId,
        summary: messages.join("\n\n").trim(),
        usage,
        costUsd,
        errorMessage: errors.length > 0 ? errors.join("\n") : null,
        toolErrors,
    };
}
function buildOpenCodeTransientHaystack(input) {
    return [
        input.errorMessage ?? "",
        input.stdout ?? "",
        input.stderr ?? "",
    ]
        .join("\n")
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean)
        .join("\n");
}
export function isOpenCodeTransientUpstreamError(input) {
    const haystack = buildOpenCodeTransientHaystack(input);
    return OPENCODE_TRANSIENT_UPSTREAM_RE.test(haystack);
}
export function isOpenCodeUnknownSessionError(stdout, stderr) {
    const haystack = `${stdout}\n${stderr}`
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean)
        .join("\n");
    return /unknown\s+session|session\b.*\bnot\s+found|resource\s+not\s+found:.*[\\/]session[\\/].*\.json|notfounderror|no session/i.test(haystack);
}
