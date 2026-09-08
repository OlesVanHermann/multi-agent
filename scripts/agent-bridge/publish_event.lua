-- Publication atomique Redis du schema ma.bus.v1.
--
-- Les TYPE sont tous verifies avant la premiere mutation : une erreur de type
-- ne peut donc pas laisser un rapport sans reveil, ou une completion sans
-- inbox. Le contenu metier reste opaque au script.

local mode = ARGV[1]

local function key_type(key)
    local result = redis.call("TYPE", key)
    if type(result) == "table" then
        return result.ok
    end
    return result
end

local function expect_type(key, expected)
    local actual = key_type(key)
    if actual ~= "none" and actual ~= expected then
        return redis.error_reply(
            "TYPE_PRECHECK key=" .. key .. " expected=" .. expected ..
            " actual=" .. actual)
    end
    return nil
end

local function validate(spec)
    for _, item in ipairs(spec) do
        local err = expect_type(item[1], item[2])
        if err then
            return err
        end
    end
    return nil
end

if mode == "message" then
    -- KEYS: inbox, event replay ledger, shared decision slot
    -- ARGV: mode,schema,ts,maxlen,ttl,from,to,event,prompt,corr,task,cycle,
    --       requester,owner,expected,source_turn,event_id,fingerprint,
    --       decision_id,is_blocking,origin
    local err = validate({
        {KEYS[1], "stream"}, {KEYS[2], "hash"}, {KEYS[3], "hash"},
    })
    if err then return err end
    local previous = redis.call("HGET", KEYS[2], "payload_sha256")
    if previous then
        if previous == ARGV[18] then
            local replay_state = redis.call("HGET", KEYS[2], "delivery_state") or
                "DELIVERED"
            if replay_state == "DELIVERED" then
                replay_state = "ALREADY_DELIVERED"
            elseif replay_state == "SUPPRESSED_BY_DECISION" then
                replay_state = "ALREADY_SUPPRESSED_BY_DECISION"
            end
            return {
                "REPLAY", redis.call("HGET", KEYS[2], "stream_id") or "",
                ARGV[17], replay_state, ARGV[19],
            }
        end
        return {"CONFLICT", "", ARGV[17], "NOT_DELIVERED", ARGV[19]}
    end
    local stream_id = ""
    local delivery_state = "DELIVERED"
    local recipient_field = "recipient:" .. ARGV[7]
    if ARGV[20] == "1" and redis.call("HEXISTS", KEYS[3], recipient_field) == 1 then
        delivery_state = "SUPPRESSED_BY_DECISION"
    else
        stream_id = redis.call(
            "XADD", KEYS[1], "MAXLEN", "~", ARGV[4], "*",
            "schema", ARGV[2],
            "schema_version", ARGV[2],
            "event_id", ARGV[17],
            "decision_id", ARGV[19],
            "payload_sha256", ARGV[18],
            "source_turn_id", ARGV[16],
            "turn_id", ARGV[16],
            "prompt", ARGV[9],
            "from_agent", ARGV[6],
            "to_agent", ARGV[7],
            "event", ARGV[8],
            "correlation_id", ARGV[10],
            "task_id", ARGV[11],
            "cycle", ARGV[12],
            "requester", ARGV[13],
            "owner", ARGV[14],
            "origin", ARGV[21],
            "expected_event", ARGV[15],
            "timestamp", ARGV[3])
        if ARGV[20] == "1" then
            redis.call(
                "HSET", KEYS[3],
                recipient_field, ARGV[17],
                "schema_version", ARGV[2],
                "decision_id", ARGV[19],
                "source_turn_id", ARGV[16])
            redis.call("EXPIRE", KEYS[3], ARGV[5])
        end
    end
    redis.call(
        "HSET", KEYS[2],
        "payload_sha256", ARGV[18],
        "event_id", ARGV[17],
        "decision_id", ARGV[19],
        "stream_id", stream_id,
        "delivery_state", delivery_state,
        "schema_version", ARGV[2],
        "source_turn_id", ARGV[16])
    redis.call("EXPIRE", KEYS[2], ARGV[5])
    return {"CREATED", stream_id, ARGV[17], delivery_state, ARGV[19]}
end

if mode == "terminal" then
    -- KEYS: completion, inbox, terminal replay slot, decision slot,
    --       logical terminal slot (turn-independent, A9)
    local err = validate({
        {KEYS[1], "stream"}, {KEYS[2], "stream"},
        {KEYS[3], "hash"}, {KEYS[4], "hash"}, {KEYS[5], "hash"},
    })
    if err then return err end
    local previous = redis.call("HGET", KEYS[3], "payload_sha256")
    if previous then
        if previous == ARGV[20] then
            local replay_state = redis.call("HGET", KEYS[3], "delivery_state") or
                "DELIVERED"
            if replay_state == "DELIVERED" then
                replay_state = "ALREADY_DELIVERED"
            elseif replay_state == "SUPPRESSED_BY_DECISION" then
                replay_state = "ALREADY_SUPPRESSED_BY_DECISION"
            end
            return {
                "REPLAY",
                redis.call("HGET", KEYS[3], "completion_stream_id") or "",
                replay_state,
                redis.call("HGET", KEYS[3], "inbox_stream_id") or "",
                ARGV[18], ARGV[19],
            }
        end
        return {"CONFLICT", "", "NOT_DELIVERED", "", ARGV[18], ARGV[19]}
    end
    -- A9 : slot logique inter-tours. L'identité par event_id ci-dessus est
    -- scopée au tour : un done.sh émis hors-tour puis rejoué dans le tour
    -- suivant portait deux event_id et le rejeu strict passait pour un
    -- nouveau terminal (deux tours Master consommés, constat 22/08). Le
    -- slot (from,to,event,task,cycle,corr) + empreinte de contenu sans le
    -- tour ferme ce chemin : identique → ALREADY_* sans écriture ;
    -- différent → NOT_DELIVERED, l'émetteur ouvre un nouveau CYCLE/CORR.
    local slot_previous = redis.call("HGET", KEYS[5], "slot_sha256")
    if slot_previous then
        if slot_previous == ARGV[23] then
            local replay_state = redis.call("HGET", KEYS[5], "delivery_state") or
                "DELIVERED"
            if replay_state == "DELIVERED" then
                replay_state = "ALREADY_DELIVERED"
            elseif replay_state == "SUPPRESSED_BY_DECISION" then
                replay_state = "ALREADY_SUPPRESSED_BY_DECISION"
            end
            return {
                "REPLAY",
                redis.call("HGET", KEYS[5], "completion_stream_id") or "",
                replay_state,
                redis.call("HGET", KEYS[5], "inbox_stream_id") or "",
                -- L'event_id du terminal EXISTANT : le rejeu est identifié
                -- par la livraison originale, pas par sa réémission.
                redis.call("HGET", KEYS[5], "event_id") or ARGV[18],
                ARGV[19],
            }
        end
        return {"CONFLICT", "", "NOT_DELIVERED", "", ARGV[18], ARGV[19]}
    end
    local completion_id = redis.call(
        "XADD", KEYS[1], "MAXLEN", "~", ARGV[4], "*",
        "schema", ARGV[2],
        "schema_version", ARGV[2],
        "event_id", ARGV[18],
        "decision_id", ARGV[19],
        "payload_sha256", ARGV[20],
        "source_turn_id", ARGV[17],
        "turn_id", ARGV[17],
        "from", ARGV[7],
        "to", ARGV[8],
        "event", ARGV[9],
        "signal", ARGV[10],
        "origin", ARGV[22],
        "correlation_id", ARGV[12],
        "task_id", ARGV[13],
        "cycle", ARGV[14],
        "requester", ARGV[15],
        "owner", ARGV[16],
        "timestamp", ARGV[3])

    local inbox_state = "DELIVERED"
    local inbox_id = ""
    local recipient_field = "recipient:" .. ARGV[8]
    if ARGV[21] == "1" and redis.call("HEXISTS", KEYS[4], recipient_field) == 1 then
        inbox_state = "SUPPRESSED_BY_DECISION"
    else
        inbox_id = redis.call(
            "XADD", KEYS[2], "MAXLEN", "~", ARGV[5], "*",
            "schema", ARGV[2],
            "schema_version", ARGV[2],
            "event_id", ARGV[18],
            "decision_id", ARGV[19],
            "payload_sha256", ARGV[20],
            "source_turn_id", ARGV[17],
            "turn_id", ARGV[17],
            "prompt", ARGV[11],
            "from_agent", ARGV[7],
            "to_agent", ARGV[8],
            "event", ARGV[9],
            "classification", "business_terminal",
            "correlation_id", ARGV[12],
            "task_id", ARGV[13],
            "cycle", ARGV[14],
            "requester", ARGV[15],
            "owner", ARGV[16],
            "origin", ARGV[22],
            "timestamp", ARGV[3])
        if ARGV[21] == "1" then
            redis.call(
                "HSET", KEYS[4],
                recipient_field, ARGV[18],
                "schema_version", ARGV[2],
                "decision_id", ARGV[19],
                "source_turn_id", ARGV[17])
            redis.call("EXPIRE", KEYS[4], ARGV[6])
        end
    end
    redis.call(
        "HSET", KEYS[3],
        "payload_sha256", ARGV[20],
        "event_id", ARGV[18],
        "decision_id", ARGV[19],
        "completion_stream_id", completion_id,
        "inbox_stream_id", inbox_id,
        "delivery_state", inbox_state,
        "schema_version", ARGV[2],
        "source_turn_id", ARGV[17])
    redis.call("EXPIRE", KEYS[3], ARGV[6])
    -- A9 : matérialiser le slot logique dans la même transaction que la
    -- livraison — un rejeu depuis n'importe quel tour futur le trouvera.
    redis.call(
        "HSET", KEYS[5],
        "slot_sha256", ARGV[23],
        "event_id", ARGV[18],
        "decision_id", ARGV[19],
        "completion_stream_id", completion_id,
        "inbox_stream_id", inbox_id,
        "delivery_state", inbox_state,
        "schema_version", ARGV[2],
        "source_turn_id", ARGV[17])
    redis.call("EXPIRE", KEYS[5], ARGV[6])
    return {"CREATED", completion_id, inbox_state, inbox_id, ARGV[18], ARGV[19]}
end

if mode == "report" then
    -- KEYS: report stream, master inbox, sender state, report replay slot,
    --       shared decision slot
    local err = validate({
        {KEYS[1], "stream"}, {KEYS[2], "stream"}, {KEYS[3], "hash"},
        {KEYS[4], "hash"}, {KEYS[5], "hash"},
    })
    if err then return err end
    local previous = redis.call("HGET", KEYS[4], "payload_sha256")
    if previous then
        if previous == ARGV[26] then
            local replay_wake = redis.call("HGET", KEYS[4], "wake_state") or
                "NOT_APPLICABLE"
            if replay_wake == "DELIVERED" then
                replay_wake = "ALREADY_DELIVERED"
            elseif replay_wake == "SUPPRESSED_BY_DECISION" then
                replay_wake = "ALREADY_SUPPRESSED_BY_DECISION"
            end
            return {
                "REPLAY",
                redis.call("HGET", KEYS[4], "report_stream_id") or "",
                ARGV[22], ARGV[23],
                replay_wake,
                redis.call("HGET", KEYS[4], "wake_stream_id") or "",
                ARGV[24],
            }
        end
        return {"CONFLICT", "", ARGV[22], ARGV[23], "NOT_DELIVERED", "", ARGV[24]}
    end

    local report_stream_id = redis.call(
        "XADD", KEYS[1], "MAXLEN", "~", ARGV[4], "*",
        "schema", ARGV[2],
        "schema_version", ARGV[2],
        "report_id", ARGV[22],
        "source_report_id", ARGV[22],
        "event_id", ARGV[23],
        "decision_id", ARGV[24],
        "payload_sha256", ARGV[26],
        "source_turn_id", ARGV[21],
        "turn_id", ARGV[21],
        "from_agent", ARGV[7],
        "to_agent", ARGV[8],
        "event", "MASTER_REPORT",
        "classification", "supervision",
        "correlation_id", "turn-" .. ARGV[21],
        "source_correlation", ARGV[16],
        "task_id", ARGV[17],
        "cycle", ARGV[18],
        "requester", ARGV[19],
        "owner", ARGV[20],
        "status", ARGV[9],
        "summary", ARGV[10],
        "artifact", ARGV[11],
        "tests", ARGV[12],
        "next", ARGV[13],
        "duration", ARGV[14],
        "origin", ARGV[15],
        "detail", ARGV[27],
        "timestamp", ARGV[3])

    -- UN RAPPORT ENVOYÉ EST UN RAPPORT REÇU. La livraison n'est plus
    -- conditionnée par ARGV[29] : ce drapeau ne dit plus « faut-il livrer »
    -- mais seulement « ce rapport crée-t-il une obligation de décider ».
    --
    -- POURQUOI. ARGV[29] valait 1 pour BLOCKED et INFO_REQUIRED seulement.
    -- Un SUCCESS et un PARTIAL étaient donc écrits dans le flux de rapports
    -- et JAMAIS poussés vers le coordinateur : « le lot est déployé »
    -- n'atteignait pas celui qui l'avait commandé. Le retour disait
    -- state=STORED wake=NOT_APPLICABLE, ce qui ressemble à un succès — et
    -- c'en est un, pour le stockage. Un canal qui ne transporte que la
    -- détresse rend un agent silencieux tant qu'il travaille bien.
    --
    -- Les trois choses que ce drapeau commandait sont désormais séparées :
    -- la LIVRAISON est inconditionnelle, le TYPE et la DÉDUPLICATION
    -- restent attachés au caractère bloquant.
    local blocking = ARGV[29] == "1"
    local wake_state = "NOT_APPLICABLE"
    local wake_stream_id = ""
    local recipient_field = "recipient:" .. ARGV[8]
    if blocking and redis.call("HEXISTS", KEYS[5], recipient_field) == 1 then
        -- Déjà représenté par un send.sh de ce tour : ne pas compter double.
        wake_state = "SUPPRESSED_BY_DECISION"
    else
        wake_stream_id = redis.call(
            "XADD", KEYS[2], "MAXLEN", "~", ARGV[5], "*",
            "schema", ARGV[2],
            "schema_version", ARGV[2],
            "event_id", ARGV[25],
            "decision_id", ARGV[24],
            "payload_sha256", ARGV[26],
            "report_id", ARGV[22],
            "source_report_id", ARGV[22],
            "related_report_id", ARGV[22],
            "related_report_stream_id", report_stream_id,
            "source_turn_id", ARGV[21],
            "turn_id", ARGV[21],
            "prompt", ARGV[28],
            "from_agent", ARGV[7],
            "to_agent", ARGV[8],
            "event", blocking and "DECISION_REQUIRED" or "MASTER_REPORT",
            "source_event", ARGV[9],
            "status", ARGV[9],
            "classification",
                blocking and "supervision_blocking" or "supervision_progress",
            "correlation_id", ARGV[16],
            "task_id", ARGV[17],
            "cycle", ARGV[18],
            "requester", ARGV[19],
            "owner", ARGV[20],
            "detail", ARGV[27],
            "timestamp", ARGV[3])
        if blocking then
            redis.call(
                "HSET", KEYS[5],
                recipient_field, ARGV[25],
                "schema_version", ARGV[2],
                "decision_id", ARGV[24],
                "source_turn_id", ARGV[21])
            redis.call("EXPIRE", KEYS[5], ARGV[6])
        end
        wake_state = "DELIVERED"
    end

    redis.call(
        "HSET", KEYS[4],
        "payload_sha256", ARGV[26],
        "source_report_id", ARGV[22],
        "event_id", ARGV[23],
        "decision_id", ARGV[24],
        "report_stream_id", report_stream_id,
        "wake_stream_id", wake_stream_id,
        "wake_state", wake_state,
        "schema_version", ARGV[2],
        "source_turn_id", ARGV[21])
    redis.call("EXPIRE", KEYS[4], ARGV[6])
    redis.call(
        "HSET", KEYS[3],
        "last_master_report_id", ARGV[22],
        "last_master_report_source_turn_id", ARGV[21],
        "last_master_report_turn_id", ARGV[21],
        "last_master_report_stream_id", report_stream_id,
        "last_master_report_event_id", ARGV[23],
        "last_master_report_payload_sha256", ARGV[26],
        "last_master_report_at", ARGV[3],
        "last_master_report_status", ARGV[9],
        "last_master_report_delivery", wake_state,
        "last_master_report_target", ARGV[8],
        "last_master_report_schema", ARGV[2])
    return {
        "CREATED", report_stream_id, ARGV[22], ARGV[23], wake_state,
        wake_stream_id, ARGV[24],
    }
end

return redis.error_reply("INVALID_PUBLISH_MODE " .. tostring(mode))
