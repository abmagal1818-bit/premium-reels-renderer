# Premium Automarcas — Renderizador do Reel aprovado

Este serviço reproduz automaticamente o layout do vídeo aprovado:
- 1080x1920
- foto grande sem cortar o carro
- bordas sombreadas integradas ao fundo
- sem logo no topo
- preço integrado, sem caixa vermelha
- logo Premium grande na área escura inferior
- 5 fotos / 15 segundos

## 1. Criar o serviço no Render

1. Crie um repositório novo no GitHub, por exemplo: `premium-reels-renderer`.
2. Envie todos os arquivos desta pasta para o repositório.
3. No Render: New > Web Service.
4. Conecte o repositório.
5. O Render detectará o Dockerfile.
6. Faça o deploy.
7. Ao terminar, teste:
   `https://SEU-SERVICO.onrender.com/health`
   Deve responder `{"ok":true,...}`.

## 2. Alteração no n8n

NÃO altere o Webhook que já recebe o cadastro do carro.

No workflow de Reel, substitua o bloco:
`Code in JavaScript -> JSON2Video -> Wait -> checagem JSON2Video`

por UM node HTTP Request:

- Method: POST
- URL: `https://SEU-SERVICO.onrender.com/render`
- Send Body: JSON
- Body: use o conteúdo de `n8n-body.json`

A resposta será:

{
  "status": "done",
  "id": "...",
  "url": "https://SEU-SERVICO.onrender.com/videos/....mp4"
}

Essa `url` substitui a antiga `movie.url`.

## 3. Reconectar ao fluxo existente

Nos nodes do Instagram/Facebook que antes usavam:
`movie.url`

use:
`{{ $json.url }}`

Primeiro teste com IG/FB desconectados.
Quando o MP4 automático estiver visualmente igual ao aprovado, reconecte a publicação.

## Observação sobre plano gratuito

O serviço gera o vídeo de forma síncrona e pode levar alguns segundos/minutos.
No plano gratuito do Render, o serviço pode "dormir", então o primeiro Reel após um período parado pode demorar mais.
Os MP4s ficam no armazenamento efêmero do serviço; isso é suficiente para o Instagram baixar logo após a geração, mas não deve ser usado como arquivo permanente. Depois podemos enviar o MP4 final ao Supabase Storage automaticamente.
