// static/js/index.js
document.addEventListener('DOMContentLoaded', () => {
    const uploadBtn       = document.getElementById('uploadBtn');
    const datasetBtn      = document.getElementById('uploadDatasetBtn');
    const fileInput       = document.getElementById('fileInput');
    const kaggleUrlInput  = document.getElementById('kaggleUrl');
    const logEl           = document.getElementById('log');
  
    function log(msg) {
      console.log(msg);
      const p = document.createElement('div');
      p.textContent = msg;
      logEl.appendChild(p);
      logEl.scrollTop = logEl.scrollHeight;
    }
  
    uploadBtn.addEventListener('click', uploadFiles);
    datasetBtn.addEventListener('click', uploadDataset);
  
    async function uploadFiles() {
      const files = fileInput.files;
      if (!files.length) {
        alert('Please select one or more files.');
        return;
      }
  
      for (const file of files) {
        log(`Requesting presigned URL for ${file.name}...`);
        try {
          const res = await fetch('/generate_presigned_url', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              file_name: file.name,
              file_type: file.type
            })
          });
          const payload = await res.json();
          if (!res.ok) throw new Error(payload.error || 'Presign failed');
  
          const { url, fields } = payload.data;
          const form = new FormData();
          Object.entries(fields).forEach(([k, v]) => form.append(k, v));
          form.append('file', file);
  
          log(`Uploading ${file.name} to S3...`);
          const uploadRes = await fetch(url, { method: 'POST', body: form });
          if (!uploadRes.ok) throw new Error(`Upload failed (${uploadRes.status})`);
          log(`✅ ${file.name} uploaded successfully.`);
        } catch (err) {
          log(`❌ Error with ${file.name}: ${err.message}`);
        }
      }
  
      log('All files processed.');
    }
  
    async function uploadDataset() {
      const datasetUrl = kaggleUrlInput.value.trim();
      if (!datasetUrl) {
        alert('Please enter a Kaggle dataset URL.');
        return;
      }
  
      log(`Requesting presigned URLs for dataset ${datasetUrl}...`);
      try {
        const res = await fetch('/generate_presigned_url', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ dataset_url: datasetUrl })
        });
        const payload = await res.json();
        if (!res.ok) throw new Error(payload.error || 'Presign dataset failed');
  
        const entries = payload.results;
        log(`Received ${entries.length} presigned entries.`);
  
        for (const e of entries) {
          const { file_name, file_path, url, fields } = e;
          log(`Fetching local file ${file_path}...`);
          try {
            const fileRes = await fetch(`/local-files/${encodeURIComponent(file_path)}`);
            if (!fileRes.ok) throw new Error(`Fetch failed (${fileRes.status})`);
            const blob = await fileRes.blob();
  
            const form = new FormData();
            Object.entries(fields).forEach(([k, v]) => form.append(k, v));
            form.append('file', blob, file_name);
  
            log(`Uploading ${file_name}...`);
            const uploadRes = await fetch(url, { method: 'POST', body: form });
            if (!uploadRes.ok) throw new Error(`Upload failed (${uploadRes.status})`);
            log(`✅ ${file_name} uploaded.`);
  
            // clean up temp file
            const delRes = await fetch(`/local-files/${encodeURIComponent(file_path)}`, {
              method: 'DELETE'
            });
            if (delRes.ok) {
              log(`🗑️ Cleared temp file ${file_path}.`);
            } else {
              log(`⚠️ Failed to clear ${file_path} (status ${delRes.status}).`);
            }
          } catch (err) {
            log(`❌ Error processing ${file_name}: ${err.message}`);
          }
        }
  
        log('Dataset upload complete.');
      } catch (err) {
        log(`❌ ${err.message}`);
      }
    }
  });
  