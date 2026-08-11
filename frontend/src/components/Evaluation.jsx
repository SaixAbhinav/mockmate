import { ScoreRow } from './ScoreRow'

export function Evaluation({ evaluation }) {
  return (
    <section className="evaluation">
      <h2>How you did</h2>
      <p className="evaluation-assessment">{evaluation.assessment}</p>

      <p className="hint">
        answered {evaluation.coverage.answered} of {evaluation.coverage.total}
      </p>
      {Object.entries(evaluation.averages).map(([dimension, value]) => (
        <ScoreRow key={dimension} label={dimension} value={value} />
      ))}

      {evaluation.strengths.length > 0 && (
        <>
          <h3>Strengths</h3>
          <ul>{evaluation.strengths.map((s, i) => <li key={i}>{s}</li>)}</ul>
        </>
      )}

      {evaluation.improvements.length > 0 && (
        <>
          <h3>Work on</h3>
          <ul>{evaluation.improvements.map((s, i) => <li key={i}>{s}</li>)}</ul>
        </>
      )}

      <h3>Question by question</h3>
      {evaluation.questions.map((q, i) => (
        <div key={i} className="evaluation-question">
          <p className="evaluation-question-text">{q.question}</p>
          {q.skipped ? (
            <p className="hint">Not answered</p>
          ) : q.unscored ? (
            <p className="hint">Couldn't be scored</p>
          ) : (
            <>
              <ScoreRow label="correctness" value={q.correctness} />
              <ScoreRow label="depth" value={q.depth} />
              <ScoreRow label="clarity" value={q.clarity} />
              <p>{q.comment}</p>
            </>
          )}
        </div>
      ))}

      {evaluation.dsa && evaluation.dsa.questions.length > 0 && (
        <>
          <h3>Coding round</h3>
          {Object.entries(evaluation.dsa.averages).map(([dimension, value]) => (
            <ScoreRow key={dimension} label={dimension.replace('_', ' ')} value={value} />
          ))}
          <p className="hint">hints used: {evaluation.dsa.hints_used}</p>
          {evaluation.dsa.questions.map((q, i) => (
            <div key={i} className="evaluation-question">
              <p className="evaluation-question-text">{q.question}</p>
              {q.skipped ? (
                <p className="hint">Never submitted</p>
              ) : (
                <>
                  <p className={q.tests.passed === q.tests.total ? 'passed' : 'failed'}>
                    tests: {q.tests.passed}/{q.tests.total}
                    {q.tests.status !== 'ok' && ` (${q.tests.status})`}
                  </p>
                  {!q.unscored && (
                    <>
                      <ScoreRow label="code quality" value={q.code_quality} />
                      <ScoreRow label="approach" value={q.approach} />
                    </>
                  )}
                </>
              )}
              {q.unscored && <p className="hint">The code itself couldn't be scored</p>}
              {q.comment && <p>{q.comment}</p>}
              {(q.hints > 0 || q.runs > 0) && (
                <p className="hint">
                  {q.hints} hint(s) · {q.runs} test run(s) while coding
                </p>
              )}
            </div>
          ))}
        </>
      )}
    </section>
  )
}
