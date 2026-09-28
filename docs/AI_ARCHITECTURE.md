# OZ Intelligent Proposal — arquitetura aplicada

## Responsabilidades

```text
Next.js
  └─ recolhe email/chat/documentos/fotografias, mostra extração e aguarda confirmação humana
       ↓
FastAPI — AI Orchestrator
  ├─ extrai campos em JSON validado (texto e input_image pela OpenAI, quando configurada)
  ├─ aplica parser de email e regras determinísticas com precedência sobre inferências
  ├─ deteta informação em falta e valida formatos básicos
  └─ coordena a consulta técnica e devolve uma ficha estruturada
       ↓
Supabase / PostgreSQL
  ├─ dados oficiais: clientes, projetos, serviços, preços e propostas
  ├─ conhecimento técnico: patologias, causas, ensaios, severidade e soluções codificados
  └─ biblioteca privada: propostas anteriores carregadas ou geradas
       ↓
Motor de proposta
  ├─ o backend lê o catálogo e os preços; o LLM não calcula valores nem quantidades
  ├─ linhas sugeridas sem preço exigem confirmação do engenheiro
  └─ PDF com o modelo OZ, honorários e condições comerciais
```

## Fluxo de um pedido

1. A API extrai texto dos formatos suportados e envia fotografias JPG/PNG/WebP como imagens à OpenAI; todos os originais ficam no armazenamento privado. São aceites até 5 anexos e 15 MB por pedido.
2. `app.ai.orchestrator` solicita um JSON estruturado e valida-o com `RequestExtraction`.
3. `email_intake` reanalisa etiquetas explícitas e assinatura; os dados inseridos pelo gestor prevalecem sobre ambas as fontes.
4. Regras determinísticas marcam campos em falta e recusam datas/email inválidos.
5. `technical_diagnosis` consulta os registos relacionais da base técnica, pontua aderência textual e pode pedir ao LLM que escolha apenas entre códigos já encontrados. Cada correspondência inclui evidência do pedido.
6. A API guarda a análise, apresenta os candidatos e compara o pedido com a biblioteca de propostas. O gestor confirma cliente, âmbito e condições.
7. Serviços e preços vêm do catálogo Supabase. Quantidades, ensaios, IVA e totais são revistos antes da aprovação. O PDF é gerado a partir dos dados aprovados.

## Limites e guardrails

- A percentagem de aderência é uma medida de semelhança textual, não uma probabilidade clínica/estrutural nem confirmação de patologia.
- Um código técnico só pode vir das tabelas consultadas; sem suporte, a API devolve “sem correspondência”.
- Recomendações de patologia, causas, ensaios e soluções requerem vistoria e validação de engenheiro.
- Imagens podem apoiar a descrição de sinais visíveis, mas não confirmam causa, gravidade nem patologia. Pedidos com imagem exigem `OPENAI_API_KEY`; se a análise visual falhar, a API não grava um pedido como se a fotografia tivesse sido analisada.
- O modelo não recebe permissão para consultar ou alterar a base de dados, calcular preços, criar proposta aprovada ou enviar email.
- Emails da empresa cliente e do remetente são campos separados; etiquetas do texto e correções do gestor são prioritárias.
- A emissão, aprovação e envio mantêm etapas distintas; o envio exige proposta aprovada e preços preenchidos.

## Pesquisa técnica e RAG

Hoje a recuperação usa o catálogo relacional de patologias/códigos e a pesquisa textual aproximada da biblioteca de propostas. A seleção assistida da patologia recebe candidatos encontrados no catálogo; este fluxo é rastreável e não depende de embeddings.

O projeto ainda não tem ingestão de documentos técnicos arbitrários em chunks, embeddings ou pesquisa vetorial pgvector. Também não existe OCR para PDF digitalizado. Portanto, não se deve apresentar a base atual como RAG vetorial completo. Um próximo passo de RAG requer migração pgvector, indexação de chunks com origem/página, tarefa de embeddings e interface de gestão de documentos; deve manter a mesma validação por fonte e código.

## Estrutura Python

```text
apps/api/app/
├── ai/
│   └── orchestrator.py       # JSON estruturado, precedência e coordenação
├── email_intake.py           # extração determinística do corpo/assinatura
├── technical_diagnosis.py    # recuperação e seleção limitada ao catálogo técnico
├── documents.py              # texto de PDFs/DOCX/XLSX, validação de imagens e linhas MQT
├── proposals.py              # regras de negócio, catálogo, aprovação e PDF
├── proposal_library.py       # histórico privado e fuzzy match
└── proposal_pdf.py           # template e composição do documento
```

## Variáveis por proposta

`COMPANY_*`, `PROPOSAL_PAYMENT_TERMS`, `PROPOSAL_EXECUTION_PERIOD`, `PROPOSAL_QUALITY_STATEMENT` e `PROPOSAL_AFFILIATIONS_STATEMENT` alimentam o PDF. Os valores iniciais seguem o documento de referência fornecido. Confirma e ajusta estes dados no `apps/api/.env` antes de emitir uma proposta externa. A assinatura manuscrita antiga não é copiada; o documento novo inclui apenas o campo de assinatura configurado.
