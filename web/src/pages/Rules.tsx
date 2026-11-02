import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api, type RuleChanges, type RuleCondition } from "../api";
import { CategorySelect } from "../components/CategorySelect";
import { RuleFields } from "../components/RuleFields";
import { useI18n } from "../i18n";
import { invalidateLedger } from "../queries";

const EMPTY: RuleCondition = { match_field: "merchant", pattern: "", direction: null };

export function RulesPage() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const rules = useQuery({ queryKey: ["rules"], queryFn: api.rules });
  const categories = useQuery({ queryKey: ["categories"], queryFn: api.categories, staleTime: Infinity });
  const [draft, setDraft] = useState<RuleCondition>(EMPTY);
  const [categoryId, setCategoryId] = useState("");

  const onChanged = () => void invalidateLedger(queryClient);
  const create = useMutation({
    mutationFn: () => api.saveRule({ ...draft, category_id: categoryId }),
    onSuccess: () => {
      setDraft({ ...draft, pattern: "" });
      setCategoryId("");
      onChanged();
    },
  });
  const edit = useMutation({
    mutationFn: ({ id, changes }: { id: number; changes: RuleChanges }) => api.editRule(id, changes),
    onSuccess: onChanged,
  });
  const remove = useMutation({ mutationFn: (id: number) => api.deleteRule(id), onSuccess: onChanged });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (draft.pattern.trim() && categoryId) create.mutate();
  };

  return (
    <>
      <header className="page-header">
        <div>
          <h1>{t.rules.title}</h1>
          <p className="page-subtitle">{t.rules.subtitle}</p>
        </div>
      </header>

      <section className="panel">
        <div className="panel-header">
          <h2>{t.rules.newRule}</h2>
        </div>
        <form className="rule-form" onSubmit={submit}>
          <RuleFields value={draft} onChange={setDraft} />
          <div className="rule-form-target">
            <label htmlFor="new-rule-category">{t.rules.categorizeAs}</label>
            <CategorySelect
              id="new-rule-category"
              categories={categories.data ?? []}
              value={categoryId}
              onChange={setCategoryId}
              placeholder={t.rules.chooseCategory}
            />
            <button type="submit" className="primary" disabled={!draft.pattern.trim() || !categoryId || create.isPending}>
              {create.isPending ? t.common.saving : t.rules.add}
            </button>
          </div>
          {create.error && <p className="error">{create.error.message}</p>}
        </form>
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>{t.rules.yours}</h2>
          {rules.data && rules.data.length > 0 && <span className="muted">{t.rules.count(rules.data.length)}</span>}
        </div>
        {(edit.error ?? remove.error) && <p className="error small">{(edit.error ?? remove.error)?.message}</p>}
        {rules.data && rules.data.length > 0 ? (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t.rules.condition}</th>
                  <th>{t.rules.category}</th>
                  <th className="num">{t.rules.appliesTo}</th>
                  <th>
                    <span className="visually-hidden">{t.rules.actions}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rules.data.map((rule) => (
                  <tr key={rule.id}>
                    <td className="wrap">
                      {t.rules.match[rule.match_field]} <strong>{rule.pattern}</strong>
                      {rule.direction && <span className="tag">{t.rules.direction[rule.direction]}</span>}
                    </td>
                    <td>
                      <CategorySelect
                        label={t.rules.categoryFor(rule.pattern)}
                        categories={categories.data ?? []}
                        value={rule.category_id}
                        onChange={(id) => edit.mutate({ id: rule.id, changes: { category_id: id } })}
                      />
                    </td>
                    <td className="num">{t.rules.transactions(rule.transaction_count)}</td>
                    <td className="row-actions">
                      <button
                        type="button"
                        className="text-button danger"
                        disabled={remove.isPending}
                        onClick={() => {
                          if (window.confirm(t.rules.confirmDelete(`${t.rules.match[rule.match_field]} ${rule.pattern}`))) {
                            remove.mutate(rule.id);
                          }
                        }}
                      >
                        {t.rules.delete}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="empty">{rules.isPending ? t.common.loading : t.rules.empty}</p>
        )}
      </section>
    </>
  );
}
