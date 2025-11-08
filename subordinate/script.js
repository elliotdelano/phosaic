async function generateQRCode() {
    try {
        // In a real application, you would fetch this from your server
        const uniqueId = await fetchUniqueId();
        const screenWidth = window.screen.width;
        const screenHeight = window.screen.height;

        const data = JSON.stringify({
            id: uniqueId,
            width: screenWidth,
            height: screenHeight
        });

        const qr = qrcode(0, 'H');
        qr.addData(data);
        qr.make();

        const qrCodeElement = document.getElementById('qrcode');
        qrCodeElement.innerHTML = qr.createImgTag(10, 0);

    } catch (error) {
        console.error('Error generating QR code:', error);
        // Handle the error appropriately in a real application
    }
}

async function fetchUniqueId() {
    // This is a mock function. In a real application, you would
    // make a network request to your server to get a unique ID.
    return new Promise(resolve => {
        setTimeout(() => {
            resolve('a' + Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15));
        }, 500);
    });
}

generateQRCode();
