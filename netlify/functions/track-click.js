// netlify/functions/track-click.js

exports.handler = async (event, context) => {
    const { clickedUrl } = JSON.parse(event.body); // Get clicked URL from the request body

    console.log(`Link clicked: ${clickedUrl}`); // Log the clicked URL (or save it to a database)

    // You can extend this to store in a database or use any analytics API here

    return {
        statusCode: 200,
        body: JSON.stringify({ message: 'Link click tracked successfully' }),
    };
};
