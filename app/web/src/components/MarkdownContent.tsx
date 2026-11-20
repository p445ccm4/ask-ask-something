"use client";

import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface MarkdownContentProps {
  content: string;
  className?: string;
}

export function MarkdownContent({ content, className = "" }: MarkdownContentProps) {
  return (
    <div className={`space-y-2 text-xs leading-relaxed text-neutral-800 ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => (
            <h1 className="mt-3 mb-1.5 text-sm font-bold text-neutral-900">{children}</h1>
          ),
          h2: ({ children }) => (
            <h2 className="mt-2.5 mb-1 text-[13px] font-bold text-neutral-900">{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 className="mt-2 mb-1 text-xs font-bold text-neutral-900">{children}</h3>
          ),
          p: ({ children }) => <p className="leading-relaxed">{children}</p>,
          ul: ({ children }) => (
            <ul className="list-disc space-y-1 pl-5">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal space-y-1 pl-5">{children}</ol>
          ),
          li: ({ children }) => <li className="leading-relaxed">{children}</li>,
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noreferrer"
              className="font-medium text-bea-blue underline decoration-bea-blue/40 underline-offset-2 hover:decoration-bea-blue"
            >
              {children}
            </a>
          ),
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-solar-orange bg-solar-yellow/10 py-1 pl-3 pr-2 text-bea-text-primary">
              {children}
            </blockquote>
          ),
          hr: () => <hr className="my-2.5 border-bea-border" />,
          table: ({ children }) => (
            <div className="my-2 overflow-x-auto rounded-lg border border-bea-border">
              <table className="w-full border-collapse text-left text-[11px]">
                {children}
              </table>
            </div>
          ),
          thead: ({ children }) => (
            <thead className="bg-bea-canvas font-semibold text-neutral-800">
              {children}
            </thead>
          ),
          th: ({ children }) => (
            <th className="border-b border-bea-border px-2.5 py-1.5">{children}</th>
          ),
          td: ({ children }) => (
            <td className="border-t border-bea-border px-2.5 py-1.5 align-top">
              {children}
            </td>
          ),
          pre: ({ children }) => (
            <pre className="my-2 overflow-x-auto rounded-lg border border-bea-border bg-bea-canvas/80 p-2.5 font-mono text-[11px] leading-5 text-neutral-800">
              {children}
            </pre>
          ),
          code: ({ className: codeClass, children }) => {
            const isBlock = Boolean(codeClass && codeClass.includes("language-"));
            if (isBlock) {
              return <code className="font-mono text-[11px]">{children}</code>;
            }
            return (
              <code className="rounded bg-bea-canvas px-1 py-0.5 font-mono text-[11px] text-bea-teal">
                {children}
              </code>
            );
          },
          strong: ({ children }) => (
            <strong className="font-semibold text-neutral-900">{children}</strong>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

