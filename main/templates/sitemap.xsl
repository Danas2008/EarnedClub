<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet
    version="1.0"
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
    xmlns:s="http://www.sitemaps.org/schemas/sitemap/0.9"
>
    <xsl:output method="html" encoding="UTF-8" indent="yes"/>

    <xsl:template match="/">
        <html lang="en">
            <head>
                <meta charset="UTF-8"/>
                <meta name="viewport" content="width=device-width, initial-scale=1"/>
                <title>Earned Club Sitemap</title>
                <style>
                    :root {
                        --bg: #0c1117;
                        --panel: #121922;
                        --panel-soft: rgba(255, 255, 255, 0.04);
                        --line: rgba(255, 255, 255, 0.1);
                        --text: #f5f7fb;
                        --muted: rgba(245, 247, 251, 0.7);
                        --accent: #f7b733;
                        --accent-2: #fc4a1a;
                    }

                    * {
                        box-sizing: border-box;
                    }

                    body {
                        margin: 0;
                        min-height: 100vh;
                        color: var(--text);
                        font-family: Arial, Helvetica, sans-serif;
                        background: linear-gradient(180deg, #0a0f14 0%, #101821 100%);
                    }

                    a {
                        color: inherit;
                    }

                    .shell {
                        width: min(1120px, calc(100% - 32px));
                        margin: 0 auto;
                        padding: 42px 0;
                    }

                    .hero {
                        margin-bottom: 22px;
                        padding: 24px;
                        border: 1px solid var(--line);
                        border-radius: 8px;
                        background: linear-gradient(135deg, rgba(247, 183, 51, 0.12), rgba(252, 74, 26, 0.08)), var(--panel);
                    }

                    .eyebrow {
                        margin-bottom: 10px;
                        color: var(--accent);
                        font-size: 0.82rem;
                        font-weight: 800;
                        letter-spacing: 0.12em;
                        text-transform: uppercase;
                    }

                    h1 {
                        margin: 0 0 10px;
                        font-size: clamp(2rem, 6vw, 3.4rem);
                        line-height: 1;
                    }

                    p {
                        max-width: 720px;
                        margin: 0;
                        color: var(--muted);
                        font-size: 1rem;
                        line-height: 1.55;
                    }

                    .summary {
                        display: inline-flex;
                        gap: 10px;
                        align-items: center;
                        margin-top: 18px;
                        padding: 9px 12px;
                        border: 1px solid rgba(247, 183, 51, 0.28);
                        border-radius: 8px;
                        background: rgba(247, 183, 51, 0.1);
                        font-weight: 800;
                    }

                    .table-wrap {
                        overflow-x: auto;
                        border: 1px solid var(--line);
                        border-radius: 8px;
                        background: var(--panel);
                    }

                    table {
                        width: 100%;
                        border-collapse: collapse;
                    }

                    th,
                    td {
                        padding: 14px 16px;
                        border-bottom: 1px solid var(--line);
                        text-align: left;
                        vertical-align: top;
                    }

                    th {
                        color: var(--muted);
                        font-size: 0.8rem;
                        letter-spacing: 0.1em;
                        text-transform: uppercase;
                    }

                    tr:last-child td {
                        border-bottom: 0;
                    }

                    tbody tr:hover {
                        background: var(--panel-soft);
                    }

                    .url {
                        color: var(--accent);
                        font-weight: 800;
                        overflow-wrap: anywhere;
                    }

                    .muted {
                        color: var(--muted);
                    }

                    .pill {
                        display: inline-flex;
                        min-width: 52px;
                        justify-content: center;
                        padding: 5px 8px;
                        border-radius: 8px;
                        background: rgba(255, 255, 255, 0.06);
                        color: var(--text);
                        font-weight: 800;
                    }

                    @media (max-width: 680px) {
                        th:nth-child(2),
                        td:nth-child(2),
                        th:nth-child(3),
                        td:nth-child(3) {
                            display: none;
                        }
                    }
                </style>
            </head>
            <body>
                <main class="shell">
                    <section class="hero">
                        <div class="eyebrow">XML Sitemap</div>
                        <h1>Earned Club Sitemap</h1>
                        <p>This machine-readable sitemap helps search engines discover public Earned Club pages, leaderboard resources, and athlete profiles.</p>
                        <div class="summary">
                            <span class="pill"><xsl:value-of select="count(s:urlset/s:url)"/></span>
                            <span>discoverable URLs</span>
                        </div>
                    </section>

                    <div class="table-wrap">
                        <table>
                            <thead>
                                <tr>
                                    <th>URL</th>
                                    <th>Updated</th>
                                    <th>Frequency</th>
                                    <th>Priority</th>
                                </tr>
                            </thead>
                            <tbody>
                                <xsl:for-each select="s:urlset/s:url">
                                    <tr>
                                        <td>
                                            <a class="url" href="{s:loc}">
                                                <xsl:value-of select="s:loc"/>
                                            </a>
                                        </td>
                                        <td class="muted">
                                            <xsl:choose>
                                                <xsl:when test="s:lastmod">
                                                    <xsl:value-of select="s:lastmod"/>
                                                </xsl:when>
                                                <xsl:otherwise>Static</xsl:otherwise>
                                            </xsl:choose>
                                        </td>
                                        <td class="muted">
                                            <xsl:value-of select="s:changefreq"/>
                                        </td>
                                        <td>
                                            <span class="pill"><xsl:value-of select="s:priority"/></span>
                                        </td>
                                    </tr>
                                </xsl:for-each>
                            </tbody>
                        </table>
                    </div>
                </main>
            </body>
        </html>
    </xsl:template>
</xsl:stylesheet>
