const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, apikey, x-client-info, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

const nullableString = { anyOf: [{ type: "string" }, { type: "null" }] };
const field = {
  type: "object",
  properties: {
    value: nullableString,
    origin: { type: "string", enum: ["EXTRACTED", "INFERRED", "UNKNOWN"] },
  },
  required: ["value", "origin"],
  additionalProperties: false,
};

const schema = {
  type: "object",
  properties: {
    client: field,
    email: field,
    project: field,
    loc: field,
    year: field,
    caves: field,
    obj: field,
    deadline: field,
    categories: {
      type: "array",
      items: { type: "string", enum: ["CRACKING", "CONCRETE_WATER_EXPOSURE", "LEVANTAMENTO_INTEGRAL", "MONITORING"] },
    },
    constraints: { type: "array", items: { type: "string" } },
    missing_information: { type: "array", items: { type: "string" } },
  },
  required: ["client", "email", "project", "loc", "year", "caves", "obj", "deadline", "categories", "constraints", "missing_information"],
  additionalProperties: false,
};

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (req.method !== "POST") return Response.json({ error: "Método não permitido." }, { status: 405, headers: cors });

  const auth = req.headers.get("Authorization");
  if (!auth?.startsWith("Bearer ")) return Response.json({ error: "Sessão necessária." }, { status: 401, headers: cors });
  const apiKey = Deno.env.get("OPENAI_API_KEY");
  if (!apiKey) return Response.json({ error: "A função ainda não tem OPENAI_API_KEY configurada." }, { status: 503, headers: cors });

  try {
    const body = await req.json();
    const text = typeof body.text === "string" ? body.text.trim() : "";
    if (!text || text.length > 30000) return Response.json({ error: "Envie texto entre 1 e 30 000 caracteres." }, { status: 400, headers: cors });

    const response = await fetch("https://api.openai.com/v1/responses", {
      method: "POST",
      headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        model: Deno.env.get("OPENAI_MODEL") || "gpt-4.1-mini",
        input: [
          {
            role: "system",
            content: [{
              type: "input_text",
              text: "Analise o pedido de diagnóstico e ensaios de engenharia civil. Extraia factos apenas do texto fornecido. Nunca invente dados. Use INFERRED só para inferências muito seguras e não técnicas; caso contrário use null e UNKNOWN. Não recomende soluções estruturais nem aprove preços. Categorias: CRACKING para fissuração; CONCRETE_WATER_EXPOSURE para betão exposto a água, inundação ou caves submersas; LEVANTAMENTO_INTEGRAL para pedidos de levantamento integral; MONITORING para instrumentação ou monitorização. A data deve ser ISO YYYY-MM-DD se completa e inequívoca; caso contrário null. A informação em falta deve listar documentos/dados relevantes explicitamente pedidos ou necessários e ausentes no pedido. Responda segundo o JSON Schema.",
            }],
          },
          { role: "user", content: [{ type: "input_text", text }] },
        ],
        text: { format: { type: "json_schema", name: "oz_request_analysis", strict: true, schema } },
        max_output_tokens: 1200,
      }),
    });
    if (!response.ok) {
      const details = await response.text();
      console.error("OpenAI API returned", response.status, details.slice(0, 1200));
      return Response.json({ error: "A análise OpenAI falhou. Verifique a chave, o modelo e os limites da conta." }, { status: 502, headers: cors });
    }

    const result = await response.json();
    const output = result.output?.flatMap((item: { content?: Array<{ type: string; text?: string }> }) => item.content || [])
      .find((item: { type: string }) => item.type === "output_text")?.text;
    if (!output) return Response.json({ error: "A resposta da análise não continha campos estruturados." }, { status: 502, headers: cors });
    return Response.json({ analysis: JSON.parse(output) }, { headers: cors });
  } catch (error) {
    console.error("analyse-request failed", error);
    return Response.json({ error: "Não foi possível analisar este pedido." }, { status: 500, headers: cors });
  }
});
