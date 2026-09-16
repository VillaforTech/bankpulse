System.register(['react', '@grafana/data'], function (exports) {
  let React, PanelPlugin;
  return {
    setters: [
      function (module) { React = module.default || module; },
      function (module) { PanelPlugin = module.PanelPlugin; }
    ],
    execute: function () {
      const FIELD_META = {
        integrity_percent: { state: 'integrity_state', sample: 'integrity_sample', alert: 'integrity_alert', suffix: '%' },
        closure_gap: { state: 'closure_gap_state', sample: 'closure_gap_sample', alert: 'closure_gap_alert', prefix: 'USD ' },
        stale_authorized: { state: 'stale_authorized_state', sample: 'stale_authorized_sample', alert: 'stale_authorized_alert', prefix: 'USD ' },
        technical_health: { state: 'quality', sample: 'data_revision' }
      };

      function lastValue(field) {
        const values = field.values;
        return values.length ? (values.get ? values.get(values.length - 1) : values[values.length - 1]) : null;
      }

      function rowFrom(frame) {
        const row = {};
        for (const field of frame.fields || []) row[field.name] = lastValue(field);
        return row;
      }

      function currencyFrom(frame) {
        const labelled = (frame.fields || []).find(field => field.labels && field.labels.currency);
        return labelled?.labels?.currency || frame.name?.match(/currency[=:]\s*([A-Z]{3})/)?.[1] || 'USD';
      }

      function BusinessPanel(props) {
        const [now, setNow] = React.useState(Date.now());
        const latest = React.useRef({ revision: -1 });
        const lastArrival = React.useRef(0);
        React.useEffect(() => {
          const timer = setInterval(() => setNow(Date.now()), 100);
          return () => clearInterval(timer);
        }, []);

        for (const frame of props.data.series || []) {
          if (currencyFrom(frame) !== (props.options.currency || 'USD')) continue;
          const row = rowFrom(frame);
          const revision = Number(row.revision);
          if (revision > Number(latest.current.revision)) latest.current = row;
          // Equal revisions are full heartbeats. Older revisions are ignored.
          const arrival = Number(row.Time ?? row.time);
          if (revision >= Number(latest.current.revision) && Number.isFinite(arrival) && arrival > lastArrival.current) lastArrival.current = arrival;
        }

        const row = latest.current;
        const generated = Date.parse(row.generated_at);
        const stale = !Number.isFinite(generated) || now - lastArrival.current > 3000 || now - generated > 3000;
        const upstreamQuality = String(row.quality || 'INCOMPLETO');
        const quality = stale || upstreamQuality === 'DESACTUALIZADO'
          ? 'DESACTUALIZADO'
          : upstreamQuality === 'INCOMPLETO' || Number(row.complete) !== 1 || Number(row.valid) !== 1
            ? 'INCOMPLETO'
            : 'ACTUAL';
        const key = props.options.field || 'integrity_percent';
        const meta = FIELD_META[key] || {};
        const state = String(row[meta.state] || 'SIN MUESTRA');
        const sample = Number(row[meta.sample] || 0);
        const noSample = key === 'integrity_percent' && (state === 'SIN MUESTRA' || Number(row[key]) < 0);
        const alertCode = meta.alert ? Number(row[meta.alert]) : -1;
        const alert = alertCode === 1;
        let value = 'SIN MUESTRA';
        if (quality !== 'ACTUAL') value = quality;
        else if (key === 'technical_health') value = Number(row.technical_health) === 1 ? 'UP' : 'DOWN';
        else if (!noSample && row[key] != null) {
          value = (meta.prefix ? (props.options.currency || 'USD') + ' ' : '') + Number(row[key]).toLocaleString('es-EC', { maximumFractionDigits: 2 }) + (meta.suffix || '');
        }
        const color = quality !== 'ACTUAL' ? '#f2c96d' : noSample ? '#b7b7b7' : alert ? '#ff7373' : '#73d9a6';
        const alertText = key === 'technical_health'
          ? (Number(row.technical_health) === 1 ? 'CONECTADO' : 'DESCONECTADO')
          : quality !== 'ACTUAL' || alertCode < 0 ? 'ALERTA SIN ESTADO' : alert ? 'ALERTA ACTIVA' : 'ALERTA RESUELTA';
        const ageSeconds = Number.isFinite(generated) ? Math.max(0, (now - generated) / 1000).toFixed(1) : '—';

        return React.createElement('section', {
          style: { padding: '14px', height: '100%', overflow: 'auto' },
          'data-bankpulse-panel': key,
          'data-revision': String(row.revision || ''),
          'data-event-id': row.source_event_id || '',
          'data-correlation-id': row.correlation_id || '',
          'data-quality': quality,
          'data-correct': String(quality === 'ACTUAL' && !noSample)
        },
          React.createElement('div', { style: { color, fontSize: '30px', fontWeight: 650 } }, value),
          React.createElement('div', { style: { color, fontSize: '12px', marginTop: '3px' } }, state + ' · ' + alertText),
          React.createElement('div', { style: { fontSize: '11px', marginTop: '10px' } }, 'Muestra ' + sample + ' · revisión ' + (row.revision || '—')),
          React.createElement('div', { style: { fontSize: '10px', overflowWrap: 'anywhere' } }, 'Evento ' + (row.source_event_id || 'esperando bootstrap')),
          React.createElement('div', { style: { fontSize: '10px', overflowWrap: 'anywhere' } }, 'Correlación ' + (row.correlation_id || 'no disponible')),
          React.createElement('div', { style: { fontSize: '10px' } }, 'Fuente ' + (row.source || 'business-analytics') + ' · frescura ' + ageSeconds + ' s'),
          React.createElement('div', { style: { fontSize: '10px' } }, row.generated_at || '')
        );
      }

      exports('plugin', new PanelPlugin(BusinessPanel).setPanelOptions(builder => builder
        .addTextInput({ path: 'field', name: 'Campo', defaultValue: 'integrity_percent' })
        .addTextInput({ path: 'currency', name: 'Moneda', defaultValue: 'USD' })));
    }
  };
});
