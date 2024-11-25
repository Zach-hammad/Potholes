async function uploadFiles() {
    const files = document.getElementById('fileInput').files;

    for (let file of files) {
        const response = await fetch('/generate_presigned_url', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                'file_name': file.name,
                'file_type': file.type
            })
        });
        const data = await response.json()

        if (response.ok) {
            const presignedPostData = data.data;
            const formData = new FormData();
            Object.entries(presignedPostData.fields).forEach(([key, value]) => {
                formData.append(key, value);
            });
            formData.append('file', file)

            const uploadResponse = await fetch(presignedPostData.url, {
                method: 'POST',
                body: formData
            });

            if (uploadResponse.ok) {
                console.log('File ${file.name} uploaded');
            } else {
                console.error('Failed');
            }

        } else {
            console.error('Error presigned')
        }
    }
}
async function uploadDataset() {
    const kaggleUrl = document.getElementById('kaggleUrl').value;

    const response = await fetch('/generate_presigned_url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            'dataset_url': kaggleUrl
        })
    });
    const data = await response.json()

    if (response.ok) {
        
    }
    //     const presignedPostData = data.data;
    //     const formData = new FormData();
    //     Object.entries(presignedPostData.fields).forEach(([key, value]) => {
    //         formData.append(key, value);
    //     });
    //     formData.append('file', file)

    //     const uploadResponse = await fetch(presignedPostData.url, {
    //         method: 'POST',
    //         body: formData
    //     });

    //     if (uploadResponse.ok) {
    //         console.log('File ${file.name} uploaded');
    //     } else {
    //         console.error('Failed');
    //     }

    // } else {
    //     console.error('Error presigned')
    // }
}
